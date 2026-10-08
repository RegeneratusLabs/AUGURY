package au.org.regeneratus.augury.vision

/**
 * AUGURY — [VisionJson]
 *
 * A minimal recursive-descent JSON reader for the two small documents the vision
 * path parses at runtime: the app manifest (`data/app/manifest.json`) and the
 * index's `keys.json`.
 *
 * Why not `org.json`: it is an Android framework class, and this package must be
 * exercisable by plain JVM unit tests (`:app:testDebugUnitTest`, no device, no
 * Robolectric) — the stub `android.jar` used for unit tests throws on every
 * `org.json` call.
 *
 * Why not the core package's parser: `au.org.regeneratus.augury.core` owns its
 * own reader and is a different workstream's surface. The vision path is kept
 * self-contained so it can be loaded, tested and reasoned about without the
 * species database.
 *
 * The parser accepts any valid JSON document. Numbers come back as [Double],
 * objects as [LinkedHashMap] (insertion order preserved — manifest order is
 * meaningful for the audit trail), arrays as [ArrayList], and `null` as `null`.
 */
internal object VisionJson {

    fun parse(text: String): Any? {
        val parser = Parser(text)
        parser.skipWhitespace()
        val value = parser.parseValue()
        parser.skipWhitespace()
        require(parser.atEnd()) { "trailing content at offset ${parser.offset}" }
        return value
    }

    private class Parser(private val text: String) {
        var offset = 0
            private set

        fun atEnd(): Boolean = offset >= text.length

        fun skipWhitespace() {
            while (offset < text.length && text[offset].isWhitespace()) offset++
        }

        fun parseValue(): Any? {
            require(offset < text.length) { "unexpected end of JSON input" }
            return when (val c = text[offset]) {
                '{' -> parseObject()
                '[' -> parseArray()
                '"' -> parseString()
                't' -> parseLiteral("true", true)
                'f' -> parseLiteral("false", false)
                'n' -> parseLiteral("null", null)
                else -> if (c == '-' || c in '0'..'9') parseNumber() else fail("unexpected '$c'")
            }
        }

        private fun parseObject(): LinkedHashMap<String, Any?> {
            expect('{')
            val out = LinkedHashMap<String, Any?>()
            skipWhitespace()
            if (peek() == '}') { offset++; return out }
            while (true) {
                skipWhitespace()
                val key = parseString()
                skipWhitespace()
                expect(':')
                skipWhitespace()
                out[key] = parseValue()
                skipWhitespace()
                when (val c = peek()) {
                    ',' -> offset++
                    '}' -> { offset++; return out }
                    else -> fail("expected ',' or '}' but found '$c'")
                }
            }
        }

        private fun parseArray(): ArrayList<Any?> {
            expect('[')
            val out = ArrayList<Any?>()
            skipWhitespace()
            if (peek() == ']') { offset++; return out }
            while (true) {
                skipWhitespace()
                out.add(parseValue())
                skipWhitespace()
                when (val c = peek()) {
                    ',' -> offset++
                    ']' -> { offset++; return out }
                    else -> fail("expected ',' or ']' but found '$c'")
                }
            }
        }

        private fun parseString(): String {
            expect('"')
            val sb = StringBuilder()
            while (true) {
                require(offset < text.length) { "unterminated string" }
                when (val c = text[offset++]) {
                    '"' -> return sb.toString()
                    '\\' -> {
                        require(offset < text.length) { "unterminated escape" }
                        when (val esc = text[offset++]) {
                            '"' -> sb.append('"')
                            '\\' -> sb.append('\\')
                            '/' -> sb.append('/')
                            'b' -> sb.append('\b')
                            'f' -> sb.append('\u000C')
                            'n' -> sb.append('\n')
                            'r' -> sb.append('\r')
                            't' -> sb.append('\t')
                            'u' -> {
                                require(offset + 4 <= text.length) { "truncated \\u escape" }
                                val hex = text.substring(offset, offset + 4)
                                offset += 4
                                sb.append(hex.toInt(16).toChar())
                            }
                            else -> fail("bad escape '\\$esc'")
                        }
                    }
                    else -> sb.append(c)
                }
            }
        }

        private fun parseNumber(): Double {
            val start = offset
            if (peek() == '-') offset++
            while (offset < text.length && text[offset] in '0'..'9') offset++
            if (offset < text.length && text[offset] == '.') {
                offset++
                while (offset < text.length && text[offset] in '0'..'9') offset++
            }
            if (offset < text.length && (text[offset] == 'e' || text[offset] == 'E')) {
                offset++
                if (offset < text.length && (text[offset] == '+' || text[offset] == '-')) offset++
                while (offset < text.length && text[offset] in '0'..'9') offset++
            }
            return text.substring(start, offset).toDouble()
        }

        private fun <T> parseLiteral(literal: String, value: T): T {
            require(text.startsWith(literal, offset)) { "expected '$literal' at offset $offset" }
            offset += literal.length
            return value
        }

        private fun peek(): Char {
            require(offset < text.length) { "unexpected end of JSON input" }
            return text[offset]
        }

        private fun expect(c: Char) {
            require(offset < text.length && text[offset] == c) {
                "expected '$c' at offset $offset"
            }
            offset++
        }

        private fun fail(message: String): Nothing = throw IllegalArgumentException("$message at offset $offset")
    }

    // ── typed accessors, used by the settings readers ────────────────────────

    @Suppress("UNCHECKED_CAST")
    fun obj(value: Any?, context: String): Map<String, Any?> =
        value as? Map<String, Any?> ?: throw VisionContractException("$context: expected a JSON object")

    @Suppress("UNCHECKED_CAST")
    fun array(value: Any?, context: String): List<Any?> =
        value as? List<Any?> ?: throw VisionContractException("$context: expected a JSON array")

    /**
     * Any [Number], not only a `Double`.
     *
     * The JSON parsers in this app produce `Double`, but a caller that rebuilds a
     * block from the *typed* manifest hands over `Int`/`Long` — and rejecting
     * those made the gateway's preprocessing block fail with a misleading
     * "expected a number". The widened check accepts exactly the same values as
     * before and one more shape that is unambiguously a number.
     */
    fun num(value: Any?, context: String): Double =
        (value as? Number)?.toDouble()
            ?: throw VisionContractException("$context: expected a number")

    fun int(value: Any?, context: String): Int = num(value, context).toInt()

    fun str(value: Any?, context: String): String =
        (value as? String) ?: throw VisionContractException("$context: expected a string")

    @Suppress("UNCHECKED_CAST")
    fun strings(value: Any?, context: String): List<String> = try {
        (value as List<Any?>).map { it as String }
    } catch (e: ClassCastException) {
        throw VisionContractException("$context: expected an array of strings", e)
    }

    /**
     * An array of numbers, accepting a quoted number too: JSON has one number
     * type but a hand-edited manifest may quote it, and a float list is not a
     * place to be strict about spelling.
     */
    @Suppress("UNCHECKED_CAST")
    fun floats(value: Any?, context: String): FloatArray = try {
        (value as List<Any?>).mapIndexed { i, v ->
            when (v) {
                is Double -> v.toFloat()
                is String -> v.toFloatOrNull()
                    ?: throw VisionContractException("$context[$i]: '${v}' is not a number")
                else -> throw VisionContractException("$context[$i]: expected a number")
            }
        }.toFloatArray()
    } catch (e: ClassCastException) {
        throw VisionContractException("$context: expected an array of numbers", e)
    }
}

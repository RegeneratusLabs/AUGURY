package au.org.regeneratus.augury.artifacts

/**
 * AUGURY — a dependency-free JSON reader/writer for the artifact manifest.
 *
 * WHY THIS EXISTS
 * ---------------
 * The app ships no JSON library: `build.gradle.kts` declares only
 * commons-compress (for the tar reader), and `org.json` is an Android platform
 * class whose unit-test stubs throw `RuntimeException("not mocked")`. The
 * artifact pipeline must be testable on a pure JVM with no device and no
 * emulator, so it carries its own ~200-line parser rather than acquiring a
 * dependency this workstream is not allowed to add.
 *
 * THE ONE NON-OBVIOUS REQUIREMENT: CANONICAL RE-SERIALISATION
 * ----------------------------------------------------------
 * `data/app/manifest.json` carries a `generation` field which the publisher
 * (`scripts/app/build_ondevice_bundle.py`) computes as:
 *
 * ```python
 * canonical_json(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":"),
 *                                  ensure_ascii=False)
 * generation = sha256(canonical_json(manifest_without_generation).encode("utf-8"))
 * ```
 *
 * Verifying that digest on-device is what turns "the file we fetched is
 * well-formed" into "the file we fetched is the file that was published": a
 * tampered manifest (an edited sha256, a swapped repo, a downgraded generation)
 * fails the digest and is rejected before a single artifact byte is fetched.
 *
 * To reproduce Python's canonical bytes *exactly* this parser keeps each JSON
 * number's **raw source literal**. Python re-emits a float with `repr()`, which
 * is the shortest round-tripping decimal — the same text the publisher wrote to
 * disk in the first place. Re-deriving the number from a `Double` and printing
 * it back would drift (exponent formatting, `1.0` vs `1`, precision), so the raw
 * literal is preserved and emitted verbatim. Strings are escaped with Python's
 * `ensure_ascii=False` rules (no `\/`, control characters as `\u00xx`, real
 * UTF-8 for everything else), and object keys are sorted by code point.
 *
 * The compatibility claim is not hand-waved: `ManifestParserTest` recomputes the
 * digest of the *shipped* `data/app/manifest.json` and of a fixture whose digest
 * was produced by CPython, and requires both to match.
 */
sealed class JsonValue {

    /** A JSON object. Key order is preserved on parse; canonical output sorts. */
    data class Obj(val entries: LinkedHashMap<String, JsonValue>) : JsonValue() {
        operator fun get(key: String): JsonValue? = entries[key]
        fun without(key: String): Obj =
            Obj(LinkedHashMap(entries).also { it.remove(key) })
    }

    /** A JSON array. */
    data class Arr(val items: List<JsonValue>) : JsonValue()

    /** A JSON string, already unescaped. */
    data class Str(val value: String) : JsonValue()

    /** A JSON number, keeping the source literal so canonical output is exact. */
    data class Num(val raw: String) : JsonValue()

    /** A JSON boolean. */
    data class Bool(val value: Boolean) : JsonValue()

    /** JSON `null`. */
    data object Null : JsonValue()
}

/** Thrown when a document is not well-formed JSON, or uses numbers JSON forbids. */
class JsonParseException(message: String) : Exception(message)

object Json {

    /** Recursion guard: a hostile document must not blow the stack. */
    const val MAX_DEPTH: Int = 64

    /**
     * Lexicographic order over Unicode **code points**, matching Python's
     * `sorted()` on `str` (and therefore `json.dumps(sort_keys=True)`) rather
     * than the JVM's UTF-16 code-unit order. Compare `"\uFFFD"` with the
     * surrogate pair for U+10000: Python puts U+FFFD first (65533 < 65536),
     * UTF-16 order puts U+10000 first (0xD800 < 0xFFFD).
     */
    private val CODE_POINT_ORDER = object : Comparator<String> {
        override fun compare(a: String, b: String): Int {
            var i = 0
            var j = 0
            while (i < a.length && j < b.length) {
                val ca = a.codePointAt(i)
                val cb = b.codePointAt(j)
                if (ca != cb) return ca - cb
                i += Character.charCount(ca)
                j += Character.charCount(cb)
            }
            return (a.length - i) - (b.length - j)
        }
    }

    // ── parsing ─────────────────────────────────────────────────────────────

    fun parse(text: String): JsonValue = Parser(text).parseDocument()

    // ── construction helpers (used for the generation record we write) ──────

    fun obj(vararg entries: Pair<String, JsonValue>): JsonValue.Obj {
        val map = LinkedHashMap<String, JsonValue>()
        for ((k, v) in entries) map[k] = v
        return JsonValue.Obj(map)
    }

    fun obj(entries: Map<String, JsonValue>): JsonValue.Obj = JsonValue.Obj(LinkedHashMap(entries))

    fun arr(items: List<JsonValue>): JsonValue.Arr = JsonValue.Arr(items)

    fun of(value: String?): JsonValue = if (value == null) JsonValue.Null else JsonValue.Str(value)

    fun of(value: Boolean): JsonValue = JsonValue.Bool(value)

    fun of(value: Int): JsonValue = JsonValue.Num(value.toString())

    fun of(value: Long): JsonValue = JsonValue.Num(value.toString())

    /** Renders a double the way Python's `repr()` does for the values we emit. */
    fun of(value: Double): JsonValue {
        val asLong = value.toLong()
        val raw = if (asLong.toDouble() == value) asLong.toString() else value.toString()
        return JsonValue.Num(raw)
    }

    // ── Python-compatible canonical output ───────────────────────────────────

    /** `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. */
    fun canonical(value: JsonValue): String {
        val out = StringBuilder()
        writeCanonical(value, out)
        return out.toString()
    }

    fun canonicalBytes(value: JsonValue): ByteArray = canonical(value).toByteArray(Charsets.UTF_8)

    /**
     * Human-readable output with two-space indentation. Used for the on-disk
     * generation record (never for the digest — see [canonical]).
     */
    fun pretty(value: JsonValue): String {
        val out = StringBuilder()
        writePretty(value, out, 0)
        return out.toString()
    }

    private fun writeCanonical(value: JsonValue, out: StringBuilder) {
        when (value) {
            is JsonValue.Obj -> {
                out.append('{')
                var first = true
                // Python's sort_keys=True sorts by Unicode code point. Kotlin's
                // default String order compares UTF-16 code units, which puts a
                // supplementary character (U+10000..U+10FFFF, a surrogate pair
                // starting at 0xD800) *before* a BMP character with a larger code
                // point such as U+FFFD — the opposite of Python. Since the
                // manifest generation is the digest of these canonical bytes,
                // the comparator has to match CPython exactly.
                for (key in value.entries.keys.sortedWith(CODE_POINT_ORDER)) {
                    if (!first) out.append(',')
                    first = false
                    writeString(key, out)
                    out.append(':')
                    writeCanonical(value.entries.getValue(key), out)
                }
                out.append('}')
            }
            is JsonValue.Arr -> {
                out.append('[')
                value.items.forEachIndexed { index, item ->
                    if (index > 0) out.append(',')
                    writeCanonical(item, out)
                }
                out.append(']')
            }
            is JsonValue.Str -> writeString(value.value, out)
            is JsonValue.Num -> out.append(value.raw)
            is JsonValue.Bool -> out.append(if (value.value) "true" else "false")
            JsonValue.Null -> out.append("null")
        }
    }

    private fun writePretty(value: JsonValue, out: StringBuilder, depth: Int) {
        when (value) {
            is JsonValue.Obj -> {
                if (value.entries.isEmpty()) { out.append("{}"); return }
                out.append("{\n")
                value.entries.entries.forEachIndexed { index, (k, v) ->
                    indent(out, depth + 1)
                    writeString(k, out)
                    out.append(": ")
                    writePretty(v, out, depth + 1)
                    if (index < value.entries.size - 1) out.append(',')
                    out.append('\n')
                }
                indent(out, depth); out.append('}')
            }
            is JsonValue.Arr -> {
                if (value.items.isEmpty()) { out.append("[]"); return }
                out.append("[\n")
                value.items.forEachIndexed { index, item ->
                    indent(out, depth + 1)
                    writePretty(item, out, depth + 1)
                    if (index < value.items.size - 1) out.append(',')
                    out.append('\n')
                }
                indent(out, depth); out.append(']')
            }
            is JsonValue.Str -> writeString(value.value, out)
            is JsonValue.Num -> out.append(value.raw)
            is JsonValue.Bool -> out.append(if (value.value) "true" else "false")
            JsonValue.Null -> out.append("null")
        }
    }

    private fun indent(out: StringBuilder, depth: Int) {
        for (i in 0 until depth) out.append("  ")
    }

    /**
     * Python's `json.encoder.encode_basestring` with `ensure_ascii=False`:
     * `\\` and `"` are escaped, the five short control escapes are used, every
     * other code unit below U+0020 becomes `\u00xx` (lowercase hex), and
     * everything else — including non-ASCII — is emitted literally. Note that
     * Python does *not* escape `/`, U+2028 or DEL.
     */
    private fun writeString(value: String, out: StringBuilder) {
        out.append('"')
        for (ch in value) {
            when (ch) {
                '\\' -> out.append("\\\\")
                '"' -> out.append("\\\"")
                '\n' -> out.append("\\n")
                '\r' -> out.append("\\r")
                '\t' -> out.append("\\t")
                '\b' -> out.append("\\b")
                '\u000C' -> out.append("\\f")
                else ->
                    if (ch < ' ') {
                        out.append("\\u")
                        val hex = ch.code.toString(16)
                        repeat(4 - hex.length) { out.append('0') }
                        out.append(hex)
                    } else {
                        out.append(ch)
                    }
            }
        }
        out.append('"')
    }

    // ── recursive-descent parser ────────────────────────────────────────────

    private class Parser(private val text: String) {
        private var pos = 0

        fun parseDocument(): JsonValue {
            skipWhitespace()
            val value = parseValue(0)
            skipWhitespace()
            if (pos != text.length) fail("trailing content after the top-level value")
            return value
        }

        private fun parseValue(depth: Int): JsonValue {
            if (depth > MAX_DEPTH) fail("document nests deeper than $MAX_DEPTH levels")
            if (pos >= text.length) fail("unexpected end of input")
            return when (val c = text[pos]) {
                '{' -> parseObject(depth)
                '[' -> parseArray(depth)
                '"' -> JsonValue.Str(parseString())
                't' -> { expect("true"); JsonValue.Bool(true) }
                'f' -> { expect("false"); JsonValue.Bool(false) }
                'n' -> { expect("null"); JsonValue.Null }
                else ->
                    if (c == '-' || c in '0'..'9') parseNumber()
                    else fail("unexpected character '$c'")
            }
        }

        private fun parseObject(depth: Int): JsonValue.Obj {
            pos++ // '{'
            val entries = LinkedHashMap<String, JsonValue>()
            skipWhitespace()
            if (peek() == '}') { pos++; return JsonValue.Obj(entries) }
            while (true) {
                skipWhitespace()
                if (peek() != '"') fail("expected a quoted object key")
                val key = parseString()
                skipWhitespace()
                if (peek() != ':') fail("expected ':' after object key \"$key\"")
                pos++
                skipWhitespace()
                if (entries.containsKey(key)) fail("duplicate object key \"$key\"")
                entries[key] = parseValue(depth + 1)
                skipWhitespace()
                when (peek()) {
                    ',' -> pos++
                    '}' -> { pos++; return JsonValue.Obj(entries) }
                    else -> fail("expected ',' or '}' in object")
                }
            }
        }

        private fun parseArray(depth: Int): JsonValue.Arr {
            pos++ // '['
            val items = ArrayList<JsonValue>()
            skipWhitespace()
            if (peek() == ']') { pos++; return JsonValue.Arr(items) }
            while (true) {
                skipWhitespace()
                items.add(parseValue(depth + 1))
                skipWhitespace()
                when (peek()) {
                    ',' -> pos++
                    ']' -> { pos++; return JsonValue.Arr(items) }
                    else -> fail("expected ',' or ']' in array")
                }
            }
        }

        private fun parseString(): String {
            pos++ // opening quote
            val sb = StringBuilder()
            while (true) {
                if (pos >= text.length) fail("unterminated string")
                when (val c = text[pos++]) {
                    '"' -> return sb.toString()
                    '\\' -> {
                        if (pos >= text.length) fail("unterminated escape sequence")
                        when (val esc = text[pos++]) {
                            '"' -> sb.append('"')
                            '\\' -> sb.append('\\')
                            '/' -> sb.append('/')
                            'b' -> sb.append('\b')
                            'f' -> sb.append('\u000C')
                            'n' -> sb.append('\n')
                            'r' -> sb.append('\r')
                            't' -> sb.append('\t')
                            'u' -> sb.append(parseUnicodeEscape())
                            else -> fail("invalid escape '\\$esc'")
                        }
                    }
                    else ->
                        if (c < ' ') fail("raw control character in string (0x${c.code.toString(16)})")
                        else sb.append(c)
                }
            }
        }

        private fun parseUnicodeEscape(): Char {
            if (pos + 4 > text.length) fail("truncated \\u escape")
            val hex = text.substring(pos, pos + 4)
            val code = hex.toIntOrNull(16) ?: fail("invalid \\u escape \"\\u$hex\"")
            pos += 4
            return code.toChar()
        }

        private fun parseNumber(): JsonValue.Num {
            val start = pos
            if (peek() == '-') pos++
            if (peek() == '0') {
                pos++
            } else if (peek() in '1'..'9') {
                while (peek() in '0'..'9') pos++
            } else {
                fail("invalid number")
            }
            if (peek() == '.') {
                pos++
                if (peek() !in '0'..'9') fail("invalid number: no digits after '.'")
                while (peek() in '0'..'9') pos++
            }
            if (peek() == 'e' || peek() == 'E') {
                pos++
                if (peek() == '+' || peek() == '-') pos++
                if (peek() !in '0'..'9') fail("invalid number: no digits in exponent")
                while (peek() in '0'..'9') pos++
            }
            return JsonValue.Num(text.substring(start, pos))
        }

        private fun expect(literal: String) {
            if (!text.startsWith(literal, pos)) fail("expected \"$literal\"")
            pos += literal.length
        }

        private fun peek(): Char = if (pos < text.length) text[pos] else '\u0000'

        private fun skipWhitespace() {
            while (pos < text.length && (text[pos] == ' ' || text[pos] == '\t' ||
                        text[pos] == '\n' || text[pos] == '\r')
            ) {
                pos++
            }
        }

        private fun fail(message: String): Nothing =
            throw JsonParseException("invalid JSON at offset $pos: $message")
    }
}

/**
 * Path-aware view over a [JsonValue].
 *
 * Every accessor reports the JSON path (`vision.encoders[0].sha256`) in its
 * error, so a malformed manifest produces an actionable message rather than a
 * `ClassCastException`, and every accessor is strict about types: `"1"` is not
 * an integer, `1.5` is not an integer, `null` is not a string. A manifest is a
 * signed contract; being lenient here is how a wrong value reaches the encoder.
 */
class JsonNode internal constructor(val path: String, val value: JsonValue) {

    fun isNull(): Boolean = value is JsonValue.Null

    fun obj(): JsonNode {
        if (value !is JsonValue.Obj) fail("expected an object, found ${describe(value)}")
        return this
    }

    fun entries(): Map<String, JsonValue> {
        obj()
        return (value as JsonValue.Obj).entries
    }

    /** Required field. */
    fun field(name: String): JsonNode {
        obj()
        val child = (value as JsonValue.Obj).entries[name]
            ?: fail("missing required field \"$name\"")
        return JsonNode(if (path.isEmpty()) name else "$path.$name", child)
    }

    /** Optional field; `null` both when absent and when JSON `null`. */
    fun fieldOrNull(name: String): JsonNode? {
        obj()
        val child = (value as JsonValue.Obj).entries[name] ?: return null
        if (child is JsonValue.Null) return null
        return JsonNode(if (path.isEmpty()) name else "$path.$name", child)
    }

    fun array(): List<JsonNode> {
        if (value !is JsonValue.Arr) fail("expected an array, found ${describe(value)}")
        return (value as JsonValue.Arr).items.mapIndexed { index, item -> JsonNode("$path[$index]", item) }
    }

    fun string(): String = when (val v = value) {
        is JsonValue.Str -> v.value
        else -> fail("expected a string, found ${describe(v)}")
    }

    fun stringOrNull(): String? = if (isNull()) null else string()

    fun int(): Int {
        val long = long()
        if (long < Int.MIN_VALUE || long > Int.MAX_VALUE) fail("integer $long is out of range")
        return long.toInt()
    }

    fun long(): Long {
        val num = value as? JsonValue.Num ?: fail("expected an integer, found ${describe(value)}")
        if (num.raw.contains('.') || num.raw.contains('e') || num.raw.contains('E')) {
            fail("expected an integer, found the fractional number ${num.raw}")
        }
        return num.raw.toLongOrNull() ?: fail("integer ${num.raw} is out of range")
    }

    fun double(): Double {
        val num = value as? JsonValue.Num ?: fail("expected a number, found ${describe(value)}")
        val parsed = num.raw.toDoubleOrNull() ?: fail("invalid number ${num.raw}")
        if (!parsed.isFinite()) fail("number ${num.raw} is not finite")
        return parsed
    }

    fun boolean(): Boolean {
        val bool = value as? JsonValue.Bool ?: fail("expected a boolean, found ${describe(value)}")
        return bool.value
    }

    fun require(condition: Boolean, message: String) {
        if (!condition) fail(message)
    }

    fun fail(message: String): Nothing = throw ManifestFormatException("manifest field $path: $message")

    private fun describe(v: JsonValue): String = when (v) {
        is JsonValue.Obj -> "an object"
        is JsonValue.Arr -> "an array"
        is JsonValue.Str -> "a string"
        is JsonValue.Num -> "the number ${v.raw}"
        is JsonValue.Bool -> "a boolean"
        JsonValue.Null -> "null"
    }
}

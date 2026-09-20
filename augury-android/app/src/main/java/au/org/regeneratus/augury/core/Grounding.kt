package au.org.regeneratus.augury.core

/**
 * AUGURY — [Grounding]
 *
 * Kotlin port of `scripts/grounding.py`: mechanically verify a formatter answer
 * against the database facts it was given, and repair unsupported numeric claims.
 *
 * Why this is a guard rail and not a nicety
 * -----------------------------------------
 * Running the real GGUF with the real prompt, on facts containing
 * `Soil pH: neutral to slightly acidic`, the model produced
 *
 *     "Dandelion indicates acidic conditions, likely below 6.5"
 *
 * — "6.5" appears nowhere in the input facts. The third-party field test found
 * the formatter inventing pH thresholds in 7/20 answers, unchanged by a stricter
 * system prompt. A prompt instruction does not bind a 1B model, so the guard rail
 * has to be structural:
 *
 *     compose -> verify numbers against the DB payload -> strip/repair -> return
 *
 * Algorithm (ported exactly, no stricter and no looser)
 * ----------------------------------------------------
 * * [extractNumericClaims] pulls every numeric token with a small context window.
 * * [verify] compares them with the numbers present in the injected DB text; a
 *   number the payload does not contain is *unsupported*.
 * * [repair] removes unsupported numeric clauses, preferring to *neutralise*
 *   (rewrite the fabricated threshold away, keep the true qualitative claim),
 *   then to strip the numeric span, then to drop the sentence. It never
 *   re-injects the DB value as prose — the template path exists for guaranteed
 *   faithful output, and inventing replacement prose would move the
 *   hallucination, not remove it.
 *
 * Iteration-order note: Python's `_strip_number_spans` iterates a `set`, whose
 * string iteration order is randomised per process (`PYTHONHASHSEED`), so its
 * own behaviour is not deterministic when one value is a substring of another
 * (`"6"` vs `"6.5"`). This port iterates in sorted order — the order
 * [GroundingReport.unsupportedValues] already reports. Reported, not silently
 * "aligned".
 */
object Grounding {

    /** `grounding.NUM_RE`. */
    private val NUM_RE = Regex("""(?<![\w.])(\d+(?:\.\d+)?)(?![\w])""")

    /** `grounding.CLAIM_CONTEXT_RE` — a numeric claim that carries meaning. */
    private val CLAIM_CONTEXT_RE = Regex(
        """\b(ph|acid|alkalin|neutral|calcare|limestone|chalk|salinity|ec|""" +
            """moisture|drain|waterlog|fertilit|nitrogen|phosphor|potassium|""" +
            """mm|cm|%|percent|degree|range|above|below|between|around|about)\b""",
        RegexOption.IGNORE_CASE,
    )

    /** `grounding.LOAD_BEARING_RE` — sentences whose meaning depends on the number. */
    private val LOAD_BEARING_RE = Regex(
        """\b(above|below|over|under|less than|more than|greater than|at least|""" +
            """up to|around about|approximately|pH)\b""",
        RegexOption.IGNORE_CASE,
    )

    private val SENTENCE_SPLIT_RE = Regex("""(?<=[.!?])\s+""")
    private val WS_RUN_RE = Regex("""\s{2,}""")

    /** Python's argument-less `str.split()`, i.e. **any** whitespace run. */
    private val WS_RE = Regex("""\s+""")
    private val SPACE_BEFORE_PUNCT_RE = Regex("""\s+([.,;:])""")
    private val REPEATED_PUNCT_RE = Regex("""([.,;:])\1+""")
    private val LEADING_PUNCT_RE = Regex("""^\s*[,;:\-–—]\s*""")
    private val TRAILING_PUNCT_RE = Regex("""\s*[,;:\-–—]\s*$""")

    /** `_neutralise`'s first cut: an explicit `pH <number>` threshold clause. */
    private val PH_CLAUSE_RE = Regex(
        """\s*[,;—–-]?\s*\b(?:likely|probably|usually|typically|generally|often)?\s*""" +
            """(?:above|below|over|under|around|about|approximately|at least|up to)?\s*""" +
            """(?:a\s+)?pH\s*\d+(?:\.\d+)?(?:\s*[-–to]+\s*\d+(?:\.\d+)?)?\b\.?""",
        RegexOption.IGNORE_CASE,
    )

    /** `_neutralise`'s second cut: a bare trailing numeric comparison. */
    private val BARE_COMPARISON_RE = Regex(
        """\s*[,;—–-]?\s*\b(?:likely|probably|usually|typically|generally)?\s*""" +
            """(?:above|below|over|under|around|about|approximately|at least|up to)\s+""" +
            """\d+(?:\.\d+)?\s*(?:%|mm|cm|dS/m)?\b\.?""",
        RegexOption.IGNORE_CASE,
    )

    /** One numeric token with its context, mirroring `extract_numeric_claims`. */
    data class NumericClaim(
        val value: String,
        val start: Int,
        val end: Int,
        val context: String,
    )

    /** `verify()`'s report. */
    data class GroundingReport(
        /** Every supported numeric token, in occurrence order. */
        val supported: List<String>,
        val unsupported: List<NumericClaim>,
        /** Sorted, de-duplicated values — the order [repair] excises them in. */
        val unsupportedValues: List<String>,
        val clean: Boolean,
        val payloadValues: List<String>,
    )

    /** One repair event, mirroring Python's `{action, removed, before, after}`. */
    data class GroundingRepair(
        val action: String,
        val removed: List<String>,
        val before: String,
        val after: String,
    )

    /** `repair()`'s `(cleaned_text, events)`. */
    data class GroundingResult(val text: String, val repairs: List<GroundingRepair>)

    /** `grounding.payload_numbers` — every number the injected facts contain. */
    fun payloadNumbers(payloadLines: List<String>): Set<String> =
        NUM_RE.findAll(payloadLines.joinToString(" ")).map { it.groupValues[1] }.toSet()

    /** `grounding.extract_numeric_claims`. */
    fun extractNumericClaims(answer: String): List<NumericClaim> {
        val claims = ArrayList<NumericClaim>()
        for (m in NUM_RE.findAll(answer)) {
            val s = maxOf(0, m.range.first - 60)
            val e = minOf(answer.length, m.range.last + 1 + 60)
            claims.add(
                NumericClaim(
                    value = m.groupValues[1],
                    start = m.range.first,
                    end = m.range.last + 1,
                    context = answer.substring(s, e).replace("\n", " ").trim(),
                )
            )
        }
        return claims
    }

    /** `grounding.verify` — which numbers in [answer] are absent from the payload. */
    fun verify(answer: String, payloadLines: List<String>): GroundingReport {
        val allowed = payloadNumbers(payloadLines)
        val claims = extractNumericClaims(answer)
        val unsupported = claims.filter { it.value !in allowed }
        return GroundingReport(
            supported = claims.filter { it.value in allowed }.map { it.value },
            unsupported = unsupported,
            unsupportedValues = unsupported.map { it.value }.distinct().sorted(),
            clean = unsupported.isEmpty(),
            payloadValues = allowed.sorted(),
        )
    }

    /**
     * `grounding.repair` — remove unsupported numeric claims from [answer].
     *
     * Returns the cleaned text **and** the repair events, so callers can
     * log/surface what was changed instead of hiding it.
     */
    fun repair(
        answer: String,
        payloadLines: List<String>,
        neutralise: Boolean = true,
    ): GroundingResult {
        val report = verify(answer, payloadLines)
        if (report.clean) return GroundingResult(answer, emptyList())

        val badValues = report.unsupportedValues.toSet()
        val kept = ArrayList<String>()
        val events = ArrayList<GroundingRepair>()

        for (sent in sentences(answer)) {
            val valsHere = NUM_RE.findAll(sent)
                .map { it.groupValues[1] }
                .filter { it in badValues }
                .distinct()
                .sorted()
                .toList()
            if (valsHere.isEmpty()) {
                kept.add(sent)
                continue
            }

            val candidates = ArrayList<Pair<String, String>>(3)
            if (neutralise) candidates.add("neutralised" to neutralise(sent))
            candidates.add("stripped" to stripNumberSpans(sent, valsHere))
            candidates.add("dropped_sentence" to "")

            for ((action, newSent) in candidates) {
                if (action != "dropped_sentence") {
                    // A candidate is acceptable if it no longer contains a bad value.
                    val stillBad = NUM_RE.findAll(newSent).any { it.groupValues[1] in badValues }
                    if (stillBad) continue
                    if (wordCount(newSent) < 4) continue
                }
                events.add(GroundingRepair(action, valsHere, sent.trim(), newSent))
                if (newSent.isNotEmpty()) kept.add(newSent)
                break
            }
        }

        var cleaned = kept.joinToString(" ")
        cleaned = WS_RUN_RE.replace(cleaned, " ")
        return GroundingResult(cleaned.trim(), events)
    }

    /** `grounding._sentences`. */
    fun sentences(text: String): List<String> =
        SENTENCE_SPLIT_RE.split((text ?: "").trim()).filter { it.trim().isNotEmpty() }

    /** `grounding._strip_number_spans` — excise numeric spans and their unit. */
    private fun stripNumberSpans(sentence: String, badValues: List<String>): String {
        var out = sentence
        for (value in badValues) {
            // remove "pH 7.0", "7.0", "400 mm", "pH 6.5-7.0"
            val span = Regex(
                """(?:pH\s*)?${Regex.escape(value)}\s*(?:%|mm|cm|dS/m|EC)?""",
                RegexOption.IGNORE_CASE,
            )
            out = span.replace(out, "")
        }
        out = WS_RUN_RE.replace(out, " ")
        out = SPACE_BEFORE_PUNCT_RE.replace(out) { it.groupValues[1] }
        out = REPEATED_PUNCT_RE.replace(out) { it.groupValues[1] }
        out = LEADING_PUNCT_RE.replace(out, "")
        out = TRAILING_PUNCT_RE.replace(out, "")
        return out.trim()
    }

    /**
     * `grounding._neutralise` — rewrite a sentence that carried an invented
     * threshold so the fabricated precision is gone but the true qualitative
     * claim survives.
     *
     * ```
     * "Coolatai grass suggests alkaline or calcareous soils, likely above pH 7.0."
     *   -> "Coolatai grass suggests alkaline or calcareous soils."
     * "Lantana indicates acidic conditions, likely below 6.5."
     *   -> "Lantana indicates acidic conditions."
     * ```
     */
    private fun neutralise(sentence: String): String {
        var s = sentence.trim()
        s = PH_CLAUSE_RE.replace(s, "")
        s = BARE_COMPARISON_RE.replace(s, "")
        s = SPACE_BEFORE_PUNCT_RE.replace(s) { it.groupValues[1] }
        s = WS_RUN_RE.replace(s, " ")
        val t = s.trim()
        return t.trimEnd(',', ';', ':') + (if (t.isNotEmpty() && !t.endsWith(".")) "." else "")
    }

    /**
     * Python's `len(str.split())`.
     *
     * NOT `len(re.split(r"\s{2,}", s))`: the argument-less `str.split()` splits
     * on *every* whitespace run, so a normal sentence of single-spaced words
     * counts as one word per word. Using [WS_RUN_RE] here made every sentence
     * count as 1, which failed the `< 4 words` bar and dropped every sentence
     * that carried an unsupported number instead of neutralising or stripping it.
     */
    private fun wordCount(s: String): Int = WS_RE.split(s).count { it.isNotEmpty() }

    // CLAIM_CONTEXT_RE / LOAD_BEARING_RE are part of the ported module's surface.
    // The Python file defines them and its own docs describe them; `repair`'s
    // sentence strategy does not branch on them (that is what the docstring
    // claims, but the code uses candidate trial instead), so they are exposed for
    // callers that want the same notion of "load-bearing" the module documents.
    fun looksLoadBearing(sentence: String): Boolean = LOAD_BEARING_RE.containsMatchIn(sentence)

    fun looksLikeNumericClaim(sentence: String): Boolean = CLAIM_CONTEXT_RE.containsMatchIn(sentence)
}

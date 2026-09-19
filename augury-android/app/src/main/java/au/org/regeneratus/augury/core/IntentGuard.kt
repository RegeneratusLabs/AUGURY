package au.org.regeneratus.augury.core

/**
 * AUGURY — [IntentGuard]
 *
 * Kotlin port of `scripts/intent.py`. Classifies whether a message asks for
 * **management advice** (herbicide, spraying, dosing, lime, cultivation,
 * control) or asks what a plant **indicates** about the soil.
 *
 * Why this exists (from the Python module docstring): the third-party field test
 * found "What herbicide should I use on lantana?" was answered with a soil story,
 * because the funnel only refused when species extraction found nothing. The
 * answer contained no actual advice — the guard rail held — but it was off-topic
 * and read as the system ignoring the question.
 *
 * **Precedence is deliberate**: an explicit indicator question WINS over the
 * management classifier, because the product's purpose is indicators and the
 * no-advice guard rail still applies downstream. So
 *
 * * `"what does lime-loving capeweed indicate?"` → [INDICATOR] (answers normally)
 * * `"What herbicide should I use on lantana?"`     → [MANAGEMENT] (declined)
 *
 * Regex porting note: Python's `re.I` and Java's `CASE_INSENSITIVE` both fold
 * ASCII identically; they differ only for non-ASCII case pairs, and `\b` is
 * Unicode-aware in Python but ASCII-aware in Java by default. Every probe in
 * `tests/` is ASCII, and so are the two patterns' literals except for none.
 */
object IntentGuard {

    const val MANAGEMENT = "management"
    const val INDICATOR = "indicator"
    const val OTHER = "other"

    /** `intent.MANAGEMENT_RE` — products, amendments, and explicit action requests. */
    private val MANAGEMENT_RE = Regex(
        """\b(""" +
            // products and chemicals
            """herbicide|herbicides|weedkiller|weed killer|spray|spraying|sprayed|""" +
            """poison|chemical|glyphosate|roundup|2,?4-d|metsulfuron|paraquat|diquat|""" +
            """dose|dosage|rate per hectare|application rate|""" +
            // amendments and actions
            """lime|liming|gypsum|fertiliser|fertilizer|fertilise|fertilize|urea|superphosphate|""" +
            // explicit "should/how do I <verb>" requests
            """should i (?:apply|spray|use|spread|add|sow|plant|burn|slash|cultivat|plough|plow|rip|drain|grade|lime|fertilise|fertilize)|""" +
            """how (?:much|many) .*(?:spray|apply|spread|lime|urea|fertiliser|fertilizer|glyphosate|herbicide)|""" +
            """how do i (?:kill|control|remove|eradicate|get rid of|spray|apply)|""" +
            """how (?:can|do) i (?:kill|control|remove|eradicate)|""" +
            """best way to (?:kill|control|remove|eradicate|get rid of)|""" +
            """recommend|prescription|what should i do|""" +
            """control (?:it|them|this|the weed)|manage (?:it|them|this)|""" +
            """kill it|kill them|eradicate""" +
            """)\b""",
        RegexOption.IGNORE_CASE,
    )

    /** `intent.INDICATOR_RE` — the product's actual purpose. */
    private val INDICATOR_RE = Regex(
        """(""" +
            """\bindicat(?:e|es|ing|or|ors)\b|""" +
            """\bwhat does\b.*\b(?:mean|tell|say)\b|""" +
            """\btell me about\b(?!\s+(?:quantum|physics|politics|history|the weather))|""" +
            """\bwhat can you tell\b|""" +
            """\bsoil indicator""" +
            """)""",
        RegexOption.IGNORE_CASE,
    )

    /**
     * `intent.classify` — returns [MANAGEMENT], [INDICATOR] or [OTHER].
     *
     * Order matters: the indicator check runs first, so incidental management
     * vocabulary inside an indicator question does not decline it.
     */
    fun classify(message: String?): String {
        val text = (message ?: "").trim()
        if (text.isEmpty()) return OTHER
        if (INDICATOR_RE.containsMatchIn(text)) return INDICATOR
        if (MANAGEMENT_RE.containsMatchIn(text)) return MANAGEMENT
        return OTHER
    }

    /**
     * `intent.decline_response` — the refusal text.
     *
     * A refusal must not be a dead end: it names what it will not do and
     * redirects to the real purpose, so the user is not left at a wall.
     */
    fun declineResponse(kind: String? = MANAGEMENT): String {
        if (kind == MANAGEMENT) {
            return "I can only tell you what weeds indicate about your soil — I don't give " +
                "management, herbicide or dosing advice.\n\n" +
                "If you tell me which weeds you're seeing, I'll explain what they suggest " +
                "about moisture, pH, fertility, structure and salinity."
        }
        return "I can only help with what weeds and plants indicate about soil conditions.\n\n" +
            "Name a weed or plant and I'll explain what it says about your soil."
    }
}

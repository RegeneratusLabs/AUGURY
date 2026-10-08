package au.org.regeneratus.augury.core

/**
 * AUGURY — the reasoning-block strip, ported from `augury_funnel._strip_think`.
 *
 * MiniCPM5 (like Qwen) can wrap its private reasoning in `<think>…</think>`
 * before the answer. Python's funnel removes that block from the formatter's
 * output *before* the grounding pass sees it:
 *
 * ```python
 * re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
 * ```
 *
 * The Kotlin story path did not, so a thinking model's raw reasoning would have
 * been rendered to the user as the soil reading — and grounded as if it were the
 * answer. This is the same expression, with the same `DOTALL` (here
 * [RegexOption.DOT_MATCHES_ALL]) and the same trailing trim.
 *
 * Faithful to the reference in one deliberate detail: a draft that is *only* a
 * think block strips to `""`, not to `null`. `null` means "no model draft" and
 * selects the deterministic template; `""` means "the model said nothing", which
 * [AuguryAnswerer] handles the same way Python does. Collapsing the two would
 * silently swap the template in for a model that answered badly, and hide it.
 */
object Reasoning {

    private val THINK_BLOCK = Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL)

    /** [raw] without its `<think>…</think>` blocks, trimmed; `null` stays `null`. */
    fun stripThink(raw: String?): String? = raw?.let { THINK_BLOCK.replace(it, "").trim() }
}

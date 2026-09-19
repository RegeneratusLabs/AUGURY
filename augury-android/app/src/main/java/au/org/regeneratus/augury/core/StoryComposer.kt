package au.org.regeneratus.augury.core

import au.org.regeneratus.augury.core.SpeciesStore.ResolvedSpecies

/**
 * AUGURY — [StoryComposer]
 *
 * Kotlin port of `AuguryFunnel._compose_template` and `AuguryFunnel.compose`
 * (`scripts/augury_funnel.py`, ~lines 331-425), i.e. the deterministic,
 * 100%-faithful rendering path. There is no formatter model here: the port has
 * no GGUF, so [compose] is always the template path — exactly Python's
 * "no formatter model — using deterministic template mode".
 *
 * Rendering rules, all of them ports of the Python:
 *
 * * Indicator keys are iterated **generically**. The shipped database carries 12
 *   free-form keys today (`Moisture`, `Fertility`, `Soil pH`, `Salinity`,
 *   `Structure`, `Ph`, `General indicators`, `Species`, `Other indicators`,
 *   `Disturbance`, `Soil type`, `Organic matter`) and a new one must render with
 *   no code change. Nothing is hardcoded.
 * * `Ph` and `Soil pH` are distinct keys and both render — the Python loop's
 *   `shown` set cannot collapse them because dict keys are already unique.
 * * Empty values are skipped, and so are the literal `"not specified"` and
 *   `"none"` (case-insensitive). See [NONE_VALUE_DEVIATION].
 * * The display name is the common name, with the scientific name appended in
 *   parentheses when the scientific name is not already a substring of it.
 * * All resolved species are rendered, in order.
 * * A `genus_bucket` match is disclosed ([genusLevelNotice]) and a region
 *   fallback is disclosed ([regionFallbackNotice]) — never silently.
 */
class StoryComposer {

    /**
     * `AuguryFunnel.compose` — the response for a set of resolved species.
     *
     * @param question the user's message; accepted for signature parity with the
     *   Python (the model path uses it, the template path does not).
     */
    fun compose(results: List<ResolvedSpecies>, question: String, region: String?): String {
        if (results.isEmpty()) return NO_SPECIES_RESPONSE
        return composeTemplate(results) +
            genusLevelNotice(results) +
            regionFallbackNotice(results, region)
    }

    /**
     * `AuguryFunnel._compose_template` — one block per species, blocks separated
     * by a blank line.
     */
    fun composeTemplate(results: List<ResolvedSpecies>): String {
        val blocks = ArrayList<String>(results.size)
        for (r in results) {
            val common = r.commonNames.firstOrNull()
            val sci = r.scientificName
            val display = when {
                common != null && sci.lowercase() in common.lowercase() -> common
                common != null -> "$common ($sci)"
                else -> sci
            }
            val region = r.region.ifEmpty { "Europe" }
            val source = r.source

            val lines = ArrayList<String>()
            lines.add("**$display**")
            // Python guards with a `shown` set; indicator keys are unique in a map
            // already, so it never fires. Kept for a literal port.
            val shown = HashSet<String>()
            for ((key, value) in r.indicators) {
                if (key in shown) continue
                if (value.isEmpty()) continue
                val flat = value.trim().lowercase()
                if (flat == "not specified" || flat == "none") continue
                shown.add(key)
                lines.add("\n📋 **$key:** $value")
            }
            if (source.isNotEmpty()) {
                lines.add("\n---\n*Source: $source ($region)*")
            }
            blocks.add(lines.joinToString("\n"))
        }
        return blocks.joinToString("\n\n")
    }

    /**
     * `AuguryFunnel._genus_level_notice` — disclose a genus-level match.
     *
     * "thistles" and "soursob" legitimately resolve to genus buckets
     * (`cirsium spp`, `oxalis spp.`) because no single species is implied. The
     * answer must not read as if a species had been pinned down: indicator values
     * for a genus are not necessarily those of any one species in it.
     */
    fun genusLevelNotice(results: List<ResolvedSpecies>): String {
        val genus = results.filter { it.specificity == "genus_bucket" }
        if (genus.isEmpty()) return ""
        val names = genus.joinToString(", ") { it.scientificName }
        return "\n\n---\n*Note: $names is a genus-level match — your description " +
            "matches the group rather than one species. Indicators are given for " +
            "the genus, so treat them as indicative of the group.*"
    }

    /**
     * `AuguryFunnel._region_fallback_notice` — disclose that the served region is
     * not the requested one. The flag existed in the Python but was never
     * surfaced, so UK data could be passed off to an Australian user as local.
     * Silence here is the failure mode.
     */
    fun regionFallbackNotice(results: List<ResolvedSpecies>, region: String?): String {
        val fellBack = results.filter { it.regionFallback }
        if (fellBack.isEmpty()) return ""
        val served = fellBack.map { it.region.ifEmpty { "?" } }.distinct().sorted()
        val wanted = fellBack[0].requestedRegion?.takeIf { it.isNotEmpty() }
            ?: region?.takeIf { it.isNotEmpty() }
            ?: "your region"
        return "\n\n---\n*Note: no $wanted indicator data for " +
            fellBack.joinToString(", ") { it.scientificName } +
            " — showing ${served.joinToString(", ")} data instead. Treat it as " +
            "indicative only; it was not recorded for $wanted.*"
    }

    /**
     * `AuguryFunnel._compose_with_model`'s `fact_lines` — the exact strings the
     * grounding pass compares numbers against. Kept beside the renderer so the
     * two can never drift apart.
     */
    fun factLines(results: List<ResolvedSpecies>): List<String> {
        val out = ArrayList<String>()
        for (r in results) {
            for ((k, v) in r.indicators) {
                if (v.isEmpty()) continue
                val flat = v.trim().lowercase()
                if (flat == "not specified" || flat == "none") continue
                out.add("- $k: $v")
            }
        }
        return out
    }

    companion object {
        /** `AuguryFunnel.compose([])` — the deterministic no-data refusal. */
        const val NO_SPECIES_RESPONSE: String =
            "I couldn't find a plant species in your message that I have " +
                "indicator data for. Try asking about a specific weed or plant — " +
                "e.g. \"What does Yorkshire fog indicate?\" or \"Tell me about " +
                "dandelions as a soil indicator.\""

        /** `AuguryFunnel.answer("")` — the empty-message refusal. */
        const val EMPTY_MESSAGE_RESPONSE: String =
            "Please ask about a weed or plant — e.g. \"What does Yorkshire fog indicate?\""

        /**
         * Documented deviation from `_compose_template`.
         *
         * The Python template skips only the literal `"not specified"`; the
         * literal `"none"` is skipped only on the model path
         * (`_compose_with_model`'s `fact_lines`). The shipped database contains
         * 103 indicator values of exactly `"none"` which render today as
         * `📋 **Salinity:** None`. The port follows the task specification and
         * skips both spellings in the rendered story, while passing the raw
         * indicator dictionary through verbatim.
         */
        const val NONE_VALUE_DEVIATION: String =
            "template path skips \"none\" as well as \"not specified\" " +
                "(Python's _compose_template skips only \"not specified\")"
    }
}

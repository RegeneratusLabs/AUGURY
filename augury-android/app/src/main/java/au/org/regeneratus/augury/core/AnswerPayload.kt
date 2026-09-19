package au.org.regeneratus.augury.core

import au.org.regeneratus.augury.core.SpeciesStore.MatchInfo
import au.org.regeneratus.augury.core.SpeciesStore.ResolvedSpecies

/**
 * AUGURY — [AnswerPayload] and [AuguryAnswerer]
 *
 * The result contract, mirroring `AuguryFunnel.answer()`'s return dict:
 *
 * ```
 * {response, species: [str], matches: [...], refused: bool,
 *  refused_reason: "management" | "no_species" | "empty" | None,
 *  intent: "management" | "indicator" | "other",
 *  grounding_repairs: [{action, removed, before, after}, ...]}
 * ```
 *
 * [AuguryAnswerer] is the port of `answer()`'s guard-rail ordering:
 *
 * 1. an empty message is refused with `reason = "empty"`;
 * 2. intent is classified **before** anything else, and a management/advice
 *    request is declined with `reason = "management"` even though the species
 *    would resolve perfectly well — `IntentGuard` deliberately lets an explicit
 *    indicator question win;
 * 3. species that resolve to no indicator data are refused with
 *    `reason = "no_species"`;
 * 4. otherwise the story is composed and returned un-refused.
 *
 * **Not ported, by instruction:** the regex species extraction
 * (`AuguryFunnel._extract_regex`). The app's picker and photo path supply
 * species directly, so [AuguryAnswerer.answer] takes them as a parameter. The
 * funnel's `_best_plant_match` / `resolve` round trip that turns each *supplied*
 * name into a database key is ported (`SpeciesStore.resolveQuery`), so a name
 * typed by a user still gets the same scoring, junk filtering and genus-bucket
 * honesty as the Python.
 *
 * @property resolved not part of the Python dict — a convenience for the UI so it
 *   can render the indicator rows without re-resolving. Never populated on a
 *   refusal.
 */
data class AnswerPayload(
    val response: String,
    val species: List<String>,
    val matches: List<MatchInfo>,
    val refused: Boolean,
    /** `"management"` | `"no_species"` | `"empty"` | `null`. */
    val refusedReason: String?,
    val intent: String,
    val groundingRepairs: List<Grounding.GroundingRepair>,
    val resolved: List<ResolvedSpecies> = emptyList(),
) {
    companion object {
        const val REASON_MANAGEMENT = "management"
        const val REASON_NO_SPECIES = "no_species"
        const val REASON_EMPTY = "empty"
    }
}

/**
 * The text pipeline, assembled from the ported parts.
 *
 * Template mode needs no model: it is deterministic and 100% faithful to the
 * database, exactly like Python's "no formatter model — using deterministic
 * template mode". When [answer] is given [modelText], that draft is composed by
 * the formatter model instead and is then run through [Grounding.repair] against
 * the injected facts (guard rail 7), with every repair reported.
 */
class AuguryAnswerer(
    private val store: SpeciesStore,
    private val composer: StoryComposer = StoryComposer(),
) {

    /**
     * Full text pipeline.
     *
     * @param message the user's raw message (used for intent and for the story's
     *   question context).
     * @param speciesNames species the picker / photo path identified. Each is
     *   resolved through [SpeciesStore.resolveQuery].
     * @param region preferred region, e.g. `"Australia"`.
     * @param modelText optional formatter-model draft. When supplied it is
     *   grounded against [StoryComposer.factLines]; when `null` the deterministic
     *   template is rendered and no repairs can occur.
     */
    fun answer(
        message: String,
        speciesNames: List<String> = emptyList(),
        region: String? = null,
        modelText: String? = null,
    ): AnswerPayload {
        val msg = (message ?: "").trim()
        if (msg.isEmpty()) {
            return AnswerPayload(
                response = StoryComposer.EMPTY_MESSAGE_RESPONSE,
                species = emptyList(), matches = emptyList(),
                refused = true, refusedReason = AnswerPayload.REASON_EMPTY,
                intent = IntentGuard.OTHER, groundingRepairs = emptyList(),
            )
        }

        // Guard rail: management / advice intent, classified BEFORE extraction.
        val intent = IntentGuard.classify(msg)
        if (intent == IntentGuard.MANAGEMENT) {
            return AnswerPayload(
                response = IntentGuard.declineResponse(IntentGuard.MANAGEMENT),
                species = emptyList(), matches = emptyList(),
                refused = true, refusedReason = AnswerPayload.REASON_MANAGEMENT,
                intent = intent, groundingRepairs = emptyList(),
            )
        }

        val results = resolveAll(speciesNames, region)
        if (results.isEmpty()) {
            return AnswerPayload(
                response = composer.compose(emptyList(), msg, region),
                species = emptyList(), matches = emptyList(),
                refused = true, refusedReason = AnswerPayload.REASON_NO_SPECIES,
                intent = intent, groundingRepairs = emptyList(),
            )
        }

        var repairs: List<Grounding.GroundingRepair> = emptyList()
        val response = if (modelText == null) {
            composer.compose(results, msg, region)
        } else {
            val grounded = Grounding.repair(modelText, composer.factLines(results))
            repairs = grounded.repairs
            grounded.text + composer.genusLevelNotice(results) +
                composer.regionFallbackNotice(results, region)
        }

        return AnswerPayload(
            response = response,
            species = results.map { it.scientificName },
            matches = results.map { it.match },
            refused = false,
            refusedReason = null,
            intent = intent,
            groundingRepairs = repairs,
            resolved = results,
        )
    }

    /** `AuguryFunnel.resolve` — resolve each supplied name, first key wins. */
    fun resolveAll(speciesNames: List<String>, region: String? = null): List<ResolvedSpecies> {
        val results = ArrayList<ResolvedSpecies>()
        val seen = HashSet<String>()
        for (name in speciesNames) {
            val resolved = store.resolveQuery(name, region) ?: continue
            if (!seen.add(resolved.match.key)) continue
            results.add(resolved)
        }
        return results
    }
}

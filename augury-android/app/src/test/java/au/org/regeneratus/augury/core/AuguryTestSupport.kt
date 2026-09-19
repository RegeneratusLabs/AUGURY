package au.org.regeneratus.augury.core

import java.io.File

/**
 * Shared fixtures for the JVM unit tests.
 *
 * Everything here is plain JVM: no `android.*`, no Robolectric, no device and no
 * emulator. The test JVM gets `augury.repo.root` from `app/build.gradle.kts`; if
 * it is missing (e.g. an IDE run) the repo root is found by walking up from the
 * working directory until `data/app/augury-ondevice.json` appears.
 */
object AuguryTestSupport {

    val repoRoot: File by lazy {
        val fromProperty = System.getProperty("augury.repo.root")?.let { File(it) }
        if (fromProperty != null && File(fromProperty, SPECIES_DB).isFile) return@lazy fromProperty
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, SPECIES_DB).isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("could not locate the AUGURY repo root from ${File("").absolutePath}")
    }

    private const val SPECIES_DB = "data/app/augury-ondevice.json"

    /** The app's shipped species database — the same file the fixture was built from. */
    val speciesDbFile: File get() = File(repoRoot, SPECIES_DB)
    val canonicalMapFile: File get() = File(repoRoot, "data/vision/canonical_map.json")
    val synonymsFile: File get() = File(repoRoot, "data/research/common_name_synonyms.json")

    /** Loaded once: parsing 990 KB of JSON per test would dominate the run. */
    val store: SpeciesStore by lazy {
        SpeciesStore.fromFiles(speciesDbFile, canonicalMapFile, synonymsFile)
    }

    /**
     * The shipped database parsed **independently** of [SpeciesStore], so tests
     * can compare the port against the raw file rather than against itself.
     */
    private val rawDb: Map<String, Any?> by lazy {
        map(Json.parse(speciesDbFile.readText()))
    }

    private val rawSpeciesByKey: LinkedHashMap<String, Map<String, Any?>> by lazy {
        val out = LinkedHashMap<String, Map<String, Any?>>()
        for (row in maps(rawDb["species"])) {
            out[(row["key"] as String).trim().lowercase()] = row
        }
        out
    }

    fun speciesKeys(): List<String> = rawSpeciesByKey.keys.toList()

    fun declaredSpecificity(key: String): String =
        str(rawSpeciesByKey[key.lowercase()]?.get("specificity")) ?: "exact_species"

    /** Raw indicator rows for one species/region, straight from the JSON file. */
    fun rawIndicators(key: String, region: String): LinkedHashMap<String, String> {
        val row = rawSpeciesByKey[key.lowercase()] ?: return LinkedHashMap()
        for (r in maps(row["regions"])) {
            if (str(r["region"]) == region) return indicators(r["indicators"])
        }
        return LinkedHashMap()
    }

    /** The Python-generated golden fixture (`tools/emit_golden_fixtures.py`). */
    val golden: Map<String, Any?> by lazy {
        val stream = AuguryTestSupport::class.java.classLoader!!
            .getResourceAsStream("golden/augury_golden_fixtures.json")
            ?: error("golden/augury_golden_fixtures.json missing from test resources")
        val text = stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        map(Json.parse(text))
    }

    /** The canonical pair registry, read from the resource the app ships. */
    val canonicalMapFromResource: Map<String, String> by lazy {
        val stream = SpeciesStore.resourceStream(SpeciesStore.CANONICAL_MAP_RESOURCE)
            ?: error("canonical_map.json missing from main resources")
        val text = stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        val canon = map(map(Json.parse(text))["canonical"])
        val out = LinkedHashMap<String, String>()
        for ((k, v) in canon) out[k] = v as String
        out
    }

    // ── typed accessors over the untyped parsed JSON ─────────────────────────

    @Suppress("UNCHECKED_CAST")
    fun map(value: Any?): Map<String, Any?> = value as? Map<String, Any?> ?: emptyMap()

    @Suppress("UNCHECKED_CAST")
    fun list(value: Any?): List<Any?> = value as? List<Any?> ?: emptyList()

    fun str(value: Any?): String? = value as? String

    fun bool(value: Any?): Boolean = value as? Boolean ?: false

    fun num(value: Any?): Double = (value as? Double) ?: 0.0

    fun strings(value: Any?): List<String> = list(value).map { it as String }

    fun maps(value: Any?): List<Map<String, Any?>> = list(value).map { map(it) }

    /** An insertion-ordered indicator map, exactly as the fixture recorded it. */
    fun indicators(value: Any?): LinkedHashMap<String, String> {
        val out = LinkedHashMap<String, String>()
        for ((k, v) in map(value)) out[k] = v as String
        return out
    }

    fun goldenList(key: String): List<Map<String, Any?>> = maps(golden[key])
}

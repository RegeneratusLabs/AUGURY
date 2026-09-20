package au.org.regeneratus.augury.artifacts

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The manifest source is configurable (base URL, repo, filename, revision, repo
 * type) with the published contract as the default. The URL shape must match
 * what `scripts/app/publish_app_hf.sh` uploads, or first launch 404s.
 */
class ManifestSourceTest {

    @Test
    fun `the default source points at the published manifest`() {
        val source = ManifestSource()
        assertEquals("RegeneratusLabs/augury-app", source.repo)
        assertEquals("manifest.json", source.filename)
        assertEquals(
            "https://huggingface.co/datasets/RegeneratusLabs/augury-app/resolve/main/manifest.json",
            source.url,
        )
    }

    @Test
    fun `every part of the source is overridable`() {
        val source = ManifestSource(
            baseUrl = "https://mirror.invalid/",
            repo = "some-org/some-repo",
            filename = "app-manifest.json",
            revision = "v3",
            repoType = HuggingFaceRepoType.MODEL,
        )
        assertEquals(
            // A MODEL repo has NO path prefix. Hugging Face resolves it at
            // /<repo>/resolve/... ; the /models/ form is a 404, which is what
            // this test previously asserted (and what made the app request the
            // 688 MB GGUF from a path that does not exist).
            "https://mirror.invalid/some-org/some-repo/resolve/v3/app-manifest.json",
            source.url,
        )
    }

    @Test
    fun `artifact urls use each artifact's own repo and the default revision when unpinned`() {
        // The formatter GGUF is published to a MODEL repo, so its URL must have
        // no prefix. Verified against the live service:
        //   /datasets/RegeneratusLabs/augury-1b/resolve/.../MiniCPM5-...gguf -> 401
        //   /RegeneratusLabs/augury-1b/resolve/.../MiniCPM5-...gguf          -> 200
        val url = HuggingFaceUrls.resolve(
            ManifestSource.DEFAULT_BASE_URL,
            HuggingFaceRepoType.MODEL,
            "RegeneratusLabs/augury-1b",
            null,
            "MiniCPM5-1B-AUGURY-Q4_K_M.gguf",
        )
        assertEquals(
            "https://huggingface.co/RegeneratusLabs/augury-1b/resolve/main/MiniCPM5-1B-AUGURY-Q4_K_M.gguf",
            url,
        )
    }

    @Test
    fun `a pinned revision is used verbatim`() {
        val url = HuggingFaceUrls.resolve(
            ManifestSource.DEFAULT_BASE_URL,
            HuggingFaceRepoType.DATASET,
            "RegeneratusLabs/augury-app",
            "342d62ab82a985fbc26e6d01c6d2953815f3a434",
            "dinov2-base-fp32.onnx",
        )
        assertEquals(
            "https://huggingface.co/datasets/RegeneratusLabs/augury-app/resolve/" +
                "342d62ab82a985fbc26e6d01c6d2953815f3a434/dinov2-base-fp32.onnx",
            url,
        )
    }

    @Test
    fun `spaces in a filename do not produce a broken url`() {
        val url = HuggingFaceUrls.resolve(
            ManifestSource.DEFAULT_BASE_URL,
            HuggingFaceRepoType.DATASET,
            "org/repo",
            "main",
            "some dir/model file.gguf",
        )
        assertEquals(
            "https://huggingface.co/datasets/org/repo/resolve/main/some%20dir/model%20file.gguf",
            url,
        )
    }

    @Test
    fun `content range is parsed in both forms`() {
        val satisfied = ContentRange.parse("bytes 100-999/1000")!!
        assertEquals(100L, satisfied.start)
        assertEquals(999L, satisfied.end)
        assertEquals(1000L, satisfied.total)

        val unsatisfied = ContentRange.parse("bytes */1000")!!
        assertEquals(null, unsatisfied.start)
        assertEquals(1000L, unsatisfied.total)
        assertEquals(true, unsatisfied.isUnsatisfied)

        assertEquals(null, ContentRange.parse(null))
        assertEquals(null, ContentRange.parse("pages 1-2/3"))
    }
}

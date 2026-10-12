package cloud.personal.sync

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class ApiClientTest {
    private class MemoryTokens(override var access: String = "a1", override var refresh: String = "r1") : TokenStore

    private lateinit var server: MockWebServer
    private lateinit var tokens: MemoryTokens
    private lateinit var api: ApiClient

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        tokens = MemoryTokens()
        api = ApiClient(server.url("/").toString(), tokens)
    }

    @After
    fun tearDown() = server.shutdown()

    private fun json(code: Int, body: String) =
        MockResponse().setResponseCode(code).setHeader("Content-Type", "application/json").setBody(body)

    @Test
    fun expiredTokenIsRefreshedAndTheRequestRepeated() {
        server.enqueue(json(401, """{"detail":"expired"}"""))
        server.enqueue(json(200, """{"access_token":"a2","refresh_token":"r2"}"""))
        server.enqueue(json(200, """{"id":"folder-1","path":"x"}"""))

        assertEquals("folder-1", api.ensureFolder("x"))
        assertEquals("a2", tokens.access)
        assertEquals("r2", tokens.refresh)
        assertEquals("Bearer a2", server.takeRequest().let { server.takeRequest(); server.takeRequest() }.getHeader("Authorization"))
    }

    @Test
    fun deadRefreshTokenIsAnAuthError() {
        server.enqueue(json(401, """{"detail":"expired"}"""))
        server.enqueue(json(401, """{"detail":"bad refresh"}"""))
        try {
            api.ensureFolder("x")
            fail("expected AuthError")
        } catch (e: AuthError) {
            assertTrue(e.message!!.contains("log in again"))
        }
    }

    @Test
    fun smallUploadIsCreateOnlyAndNameClashIsAVersionConflict() {
        server.enqueue(
            json(409, """{"detail":{"code":"version_conflict","message":"changed","file_id":"f"}}""")
        )
        try {
            api.uploadNew({ "hello".byteInputStream() }, "IMG_1.jpg", "folder-1", 5, "image/jpeg", "h")
            fail("expected VersionConflict")
        } catch (_: VersionConflict) {
        }
        val request = server.takeRequest()
        assertEquals("/api/files/upload", request.path)
        val body = request.body.readUtf8()
        assertTrue(Regex("name=\"base_version_id\"[\\s\\S]*?\r\n\r\nnone").containsMatchIn(body))
        assertTrue(body.contains("hello"))
    }

    @Test
    fun resumedChunkedUploadSendsOnlyMissingChunks() {
        val size = CHUNKED_THRESHOLD + 1
        val chunk = 4L
        server.enqueue(
            json(200, """{"id":"u1","status":"pending","chunk_size":$chunk,"missing_chunk_indices":[1,2]}""")
        )
        server.enqueue(json(200, "{}")) // chunk 1
        server.enqueue(json(200, "{}")) // chunk 2
        server.enqueue(json(200, """{"id":"file-1","content_hash":"abc"}"""))
        var sessions = mutableListOf<String?>()

        // Fake source: stream of `size` bytes is too big for a test; chunks are 4 bytes each,
        // so serve a short stream and a small declared size via the chunked path directly.
        val result = api.uploadNew(
            { ByteArray(12) { it.toByte() }.inputStream() }, "v.mp4", "folder-1",
            size = 12 + CHUNKED_THRESHOLD, mime = "video/mp4", contentHash = "abc",
            resumeId = "u1", onSession = { sessions.add(it) },
        )
        assertEquals("file-1", result.fileId)
        assertEquals(listOf<String?>(null), sessions) // existing session reused, cleared when done
        assertEquals("/api/uploads/u1", server.takeRequest().path)
        assertEquals("/api/uploads/u1/chunks/1", server.takeRequest().path)
        assertEquals("/api/uploads/u1/chunks/2", server.takeRequest().path)
        assertEquals("/api/uploads/u1/complete", server.takeRequest().path)
    }

    @Test
    fun snapshotIsRevalidatedWithEtagAndServedFromCacheOn304() {
        server.enqueue(
            json(200, """{"folders":[],"files":[{"id":"1","path":"a/b.jpg","content_hash":"h"}]}""")
                .setHeader("ETag", "\"v1\"")
        )
        server.enqueue(MockResponse().setResponseCode(304))
        assertEquals("h", api.snapshot()["a/b.jpg"]?.contentHash)
        assertEquals("h", api.snapshot()["a/b.jpg"]?.contentHash)
        server.takeRequest()
        assertEquals("\"v1\"", server.takeRequest().getHeader("If-None-Match"))
    }

    @Test
    fun unreachableServerIsApiUnavailable() {
        server.shutdown()
        try {
            api.ensureFolder("x")
            fail("expected ApiUnavailable")
        } catch (_: ApiUnavailable) {
        }
    }
}

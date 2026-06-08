package io.legado.app.help

import io.legado.app.data.entities.BaseSource
import io.legado.app.utils.ChineseUtils
import java.net.URLEncoder
import java.nio.charset.Charset
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Base64
import java.util.Date
import java.util.Locale
import java.util.SimpleTimeZone
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * JVM first slice of Reading's JsExtensions.
 *
 * Network and WebView helpers are routed to structured unsupported output until
 * the backend runtime is connected to AnalyzeRule/WebBook.
 */
@Suppress("unused")
interface JsExtensions {
    fun getSource(): BaseSource?

    fun getTag(): String?

    fun ajax(url: Any): String =
        "UNSUPPORTED:java.ajax:${url}"

    fun base64Encode(str: String): String =
        Base64.getEncoder().encodeToString(str.toByteArray(Charsets.UTF_8))

    fun base64Decode(str: String): String =
        String(Base64.getDecoder().decode(str), Charsets.UTF_8)

    fun md5(str: String): String =
        MessageDigest.getInstance("MD5")
            .digest(str.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }

    fun md5Encode(str: String): String = md5(str)

    fun md5Encode16(str: String): String =
        md5(str).substring(8, 24)

    fun hexEncodeToString(utf8: String): String =
        utf8.toByteArray(Charsets.UTF_8).joinToString("") { "%02x".format(it) }

    fun hexDecodeToString(hex: String): String =
        String(hexDecodeToByteArray(hex), Charsets.UTF_8)

    fun hexDecodeToByteArray(hex: String): ByteArray {
        val clean = hex.trim().removePrefix("0x")
        require(clean.length % 2 == 0) { "hex length must be even" }
        return clean.chunked(2)
            .map { it.toInt(16).toByte() }
            .toByteArray()
    }

    fun encodeURI(str: String): String =
        encodeURI(str, "UTF-8")

    fun encodeURI(str: String, enc: String): String =
        runCatching { URLEncoder.encode(str, enc).replace("+", "%20") }.getOrDefault("")

    fun timeFormat(time: Long): String =
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(time))

    fun timeFormatUTC(time: Long, format: String, sh: Int): String =
        SimpleDateFormat(format, Locale.getDefault()).run {
            timeZone = SimpleTimeZone(sh, "UTC")
            format(Date(time))
        }

    fun strToBytes(str: String): ByteArray =
        str.toByteArray(Charsets.UTF_8)

    fun strToBytes(str: String, charset: String): ByteArray =
        str.toByteArray(Charset.forName(charset))

    fun bytesToStr(bytes: ByteArray): String =
        String(bytes, Charsets.UTF_8)

    fun bytesToStr(bytes: ByteArray, charset: String): String =
        String(bytes, Charset.forName(charset))

    fun randomUUID(): String = UUID.randomUUID().toString()

    fun androidId(): String = "UNSUPPORTED:androidId"

    fun aesBase64DecodeToString(
        str: String,
        key: String,
        transformation: String,
        iv: String,
    ): String =
        decryptToString(Base64.getDecoder().decode(str), key, transformation, iv)

    fun desBase64DecodeToString(
        data: String,
        key: String,
        transformation: String,
        iv: String,
    ): String =
        aesBase64DecodeToString(data, key, transformation, iv)

    fun aesDecodeToString(
        str: String,
        key: String,
        transformation: String,
        iv: String,
    ): String =
        decryptToString(str.toByteArray(Charsets.UTF_8), key, transformation, iv)

    fun desDecodeToString(
        data: String,
        key: String,
        transformation: String,
        iv: String,
    ): String =
        aesDecodeToString(data, key, transformation, iv)

    fun aesEncodeToBase64String(
        data: String,
        key: String,
        transformation: String,
        iv: String,
    ): String =
        Base64.getEncoder().encodeToString(crypt(Cipher.ENCRYPT_MODE, data.toByteArray(Charsets.UTF_8), key, transformation, iv))

    fun desEncodeToBase64String(
        data: String,
        key: String,
        transformation: String,
        iv: String,
    ): String =
        aesEncodeToBase64String(data, key, transformation, iv)

    fun aesEncodeArgsBase64Str(
        data: String,
        key: String,
        mode: String,
        padding: String,
        iv: String,
    ): String =
        aesEncodeToBase64String(data, key, "AES/$mode/$padding", iv)

    fun aesDecodeArgsBase64Str(
        data: String,
        key: String,
        mode: String,
        padding: String,
        iv: String,
    ): String =
        aesBase64DecodeToString(data, key, "AES/$mode/$padding", iv)

    fun toast(msg: Any?) {
        log(msg)
    }

    fun longToast(msg: Any?) {
        log(msg)
    }

    fun log(msg: Any?): Any? = msg

    fun logType(any: Any?) {
        log(any?.javaClass?.name ?: "null")
    }

    fun t2s(text: String): String =
        ChineseUtils.t2s(text)

    fun s2t(text: String): String =
        ChineseUtils.s2t(text)

    private fun decryptToString(
        data: ByteArray,
        key: String,
        transformation: String,
        iv: String,
    ): String =
        String(crypt(Cipher.DECRYPT_MODE, data, key, transformation, iv), Charsets.UTF_8)

    private fun crypt(
        mode: Int,
        data: ByteArray,
        key: String,
        transformation: String,
        iv: String,
    ): ByteArray {
        val algorithm = transformation.substringBefore("/")
        val cipher = Cipher.getInstance(transformation)
        val secretKey = SecretKeySpec(key.toByteArray(Charsets.UTF_8), algorithm)
        if (iv.isBlank() || transformation.contains("/ECB/", ignoreCase = true)) {
            cipher.init(mode, secretKey)
        } else {
            cipher.init(mode, secretKey, IvParameterSpec(iv.toByteArray(Charsets.UTF_8)))
        }
        return cipher.doFinal(data)
    }
}

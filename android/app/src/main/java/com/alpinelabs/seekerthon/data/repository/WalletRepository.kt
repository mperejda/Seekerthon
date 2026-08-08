package com.alpinelabs.seekerthon.data.repository

import android.content.Context
import android.net.Uri
import android.util.Base64
import com.google.android.gms.tasks.Tasks
import com.google.firebase.messaging.FirebaseMessaging
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.solana.mobilewalletadapter.clientlib.ConnectionIdentity
import com.solana.mobilewalletadapter.clientlib.MobileWalletAdapter
import com.solana.mobilewalletadapter.clientlib.RpcCluster
import com.solana.mobilewalletadapter.clientlib.TransactionResult
import com.alpinelabs.seekerthon.data.remote.DeviceTokenDto
import com.alpinelabs.seekerthon.data.remote.SeekerApi
import com.alpinelabs.seekerthon.data.remote.UserCreateDto
import com.alpinelabs.seekerthon.di.TokenProvider
import com.alpinelabs.seekerthon.domain.model.AuthState
import com.alpinelabs.seekerthon.util.toUser
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import retrofit2.HttpException
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class WalletRepository @Inject constructor(
    private val api: SeekerApi,
    private val tokenProvider: TokenProvider,
    @ApplicationContext private val context: Context,
) {
    private val identityUri = Uri.parse("https://seekerthon.com")
    private val iconUri = Uri.parse("icon.png")
    private val appName = "Seekerthon"

    @Suppress("DEPRECATION")
    private fun newAdapter() = MobileWalletAdapter(
        connectionIdentity = ConnectionIdentity(
            identityUri = identityUri,
            iconUri = iconUri,
            identityName = appName,
        )
    ).also { it.rpcCluster = RpcCluster.MainnetBeta }

    suspend fun connectAndLogin(sender: ActivityResultSender): Result<AuthState> =
        withContext(Dispatchers.IO) {
            runCatching {
                val adapter = newAdapter()

                // Session 1: authorize — transact() handles authorize() internally,
                // block receives the AuthorizationResult directly.
                val publicKeyBytes = when (val r = adapter.transact(sender) { authResult ->
                    authResult.accounts.first().publicKey
                }) {
                    is TransactionResult.Success -> r.payload
                    is TransactionResult.Failure -> throw Exception("Authorization failed: ${r.message}")
                    is TransactionResult.NoWalletFound -> throw Exception("No Solana wallet found on device")
                }

                val walletAddress = publicKeyBytes.encodeBase58()

                // Fetch challenge from backend (outside the wallet session)
                val challengeDto = api.getChallenge(walletAddress)

                // Session 2: sign the challenge (adapter reuses cached authToken)
                val signature = when (val r = adapter.transact(sender) { _ ->
                    signMessagesDetached(
                        messages = arrayOf(challengeDto.challenge.toByteArray()),
                        addresses = arrayOf(publicKeyBytes),
                    )
                }) {
                    is TransactionResult.Success -> r.payload.messages.first().signatures.first()
                    is TransactionResult.Failure -> throw Exception("Signing failed: ${r.message}")
                    is TransactionResult.NoWalletFound -> throw Exception("No Solana wallet found on device")
                }

                val sigBase58 = signature.encodeBase58()

                // Exchange signed challenge for JWT
                val authToken = try {
                    api.login(
                        UserCreateDto(
                            wallet_address = walletAddress,
                            signature = sigBase58,
                            challenge = challengeDto.challenge,
                        )
                    )
                } catch (e: HttpException) {
                    val detail = try {
                        JSONObject(e.response()?.errorBody()?.string() ?: "").getString("detail")
                    } catch (_: Exception) { null }
                    throw Exception(detail ?: when (e.code()) {
                        403 -> "A Seeker Genesis Token is required to sign in."
                        503 -> "Unable to verify your Seeker Genesis Token. Please try again."
                        else -> "Login failed (${e.code()})"
                    })
                }

                tokenProvider.saveToken(authToken.access_token)

                // Register FCM token with the backend (non-fatal if it fails)
                runCatching {
                    val fcmToken = Tasks.await(FirebaseMessaging.getInstance().token)
                    api.registerDeviceToken(DeviceTokenDto(fcmToken))
                }

                AuthState(token = authToken.access_token, user = authToken.user.toUser())
            }
        }

    suspend fun signVoteMessage(
        sender: ActivityResultSender,
        voteMessage: String,
    ): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val messageBytes = voteMessage.toByteArray(Charsets.UTF_8)
            val adapter = newAdapter()

            // Session 1: authorize and get public key (same pattern as login)
            val publicKeyBytes = when (val r = adapter.transact(sender) { authResult ->
                authResult.accounts.first().publicKey
            }) {
                is TransactionResult.Success -> r.payload
                is TransactionResult.Failure -> throw Exception("Authorization failed: ${r.message}")
                is TransactionResult.NoWalletFound -> throw Exception("No Solana wallet found on device")
            }

            // Session 2: sign message (adapter reuses cached auth token)
            when (val r = adapter.transact(sender) { _ ->
                signMessagesDetached(
                    messages = arrayOf(messageBytes),
                    addresses = arrayOf(publicKeyBytes),
                )
            }) {
                is TransactionResult.Success -> {
                    val sig = r.payload.messages.first().signatures.first()
                        ?: throw Exception("Wallet returned null signature — could not sign vote message")
                    sig.encodeBase58()
                }
                is TransactionResult.Failure -> throw Exception("Signing failed: ${r.message}")
                is TransactionResult.NoWalletFound -> throw Exception("No Solana wallet found on device")
            }
        }
    }

    suspend fun signAndSendTransaction(
        sender: ActivityResultSender,
        transactionB64: String,
    ): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val txBytes = Base64.decode(transactionB64, Base64.DEFAULT)
            val adapter = newAdapter()
            // signTransactions (not signAndSendTransactions): wallet signs and returns the signed
            // bytes without submitting. The backend submits and polls for confirmation, which
            // avoids the Seed Vault null-signature bug where the wallet submits but times out
            // before returning the tx signature.
            when (val r = adapter.transact(sender) { _ ->
                signTransactions(arrayOf(txBytes))
            }) {
                is TransactionResult.Success -> {
                    val signedBytes = r.payload.signedPayloads.first()
                    Base64.encodeToString(signedBytes, Base64.NO_WRAP)
                }
                is TransactionResult.Failure -> throw Exception("Signing failed: ${r.message}")
                is TransactionResult.NoWalletFound -> throw Exception("No Solana wallet found on device")
            }
        }
    }

    suspend fun signAndSendMintTransaction(
        sender: ActivityResultSender,
        transactionB64: String,
    ): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val txBytes = Base64.decode(transactionB64, Base64.DEFAULT)
            val adapter = newAdapter()

            // Session 1: authorize and get public key
            when (val r = adapter.transact(sender) { authResult ->
                authResult.accounts.first().publicKey
            }) {
                is TransactionResult.Success -> Unit
                is TransactionResult.Failure -> throw Exception("Authorization failed: ${r.message}")
                is TransactionResult.NoWalletFound -> throw Exception("No Solana wallet found on device")
            }

            // Session 2: sign and send — wallet submits to chain, returns tx signature bytes
            when (val r = adapter.transact(sender) { _ ->
                signAndSendTransactions(arrayOf(txBytes))
            }) {
                is TransactionResult.Success -> {
                    val sigBytes = r.payload.signatures.first()
                        ?: throw Exception("Wallet returned null signature")
                    sigBytes.encodeBase58()
                }
                is TransactionResult.Failure -> throw Exception("Signing failed: ${r.message}")
                is TransactionResult.NoWalletFound -> throw Exception("No Solana wallet found on device")
            }
        }
    }

    suspend fun logout() { tokenProvider.clearToken() }
    fun isLoggedIn(): Boolean = tokenProvider.getToken() != null
    fun hasAcceptedCurrentTerms(): Boolean = tokenProvider.hasAcceptedCurrentTerms()
    suspend fun acceptCurrentTerms() = tokenProvider.acceptCurrentTerms()
}

private fun ByteArray.encodeBase58(): String {
    val alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    var intData = java.math.BigInteger(1, this)
    val sb = StringBuilder()
    val base = java.math.BigInteger.valueOf(58)
    while (intData > java.math.BigInteger.ZERO) {
        val (quotient, remainder) = intData.divideAndRemainder(base)
        sb.append(alphabet[remainder.toInt()])
        intData = quotient
    }
    for (b in this) { if (b == 0.toByte()) sb.append(alphabet[0]) else break }
    return sb.reverse().toString()
}

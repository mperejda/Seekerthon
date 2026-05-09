package com.seeker.hackathon.data.repository

import android.content.Context
import android.net.Uri
import android.util.Base64
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.solana.mobilewalletadapter.clientlib.ConnectionIdentity
import com.solana.mobilewalletadapter.clientlib.MobileWalletAdapter
import com.solana.mobilewalletadapter.clientlib.RpcCluster
import com.solana.mobilewalletadapter.clientlib.TransactionResult
import com.seeker.hackathon.data.remote.SeekerApi
import com.seeker.hackathon.data.remote.UserCreateDto
import com.seeker.hackathon.di.TokenProvider
import com.seeker.hackathon.domain.model.AuthState
import com.seeker.hackathon.util.toUser
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class WalletRepository @Inject constructor(
    private val api: SeekerApi,
    private val tokenProvider: TokenProvider,
    @ApplicationContext private val context: Context,
) {
    private val identityUri = Uri.parse("https://seekerthon.com")
    private val iconUri = Uri.parse("favicon.ico")
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
                val authToken = api.login(
                    UserCreateDto(
                        wallet_address = walletAddress,
                        signature = sigBase58,
                        challenge = challengeDto.challenge,
                    )
                )

                tokenProvider.saveToken(authToken.access_token)
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
            // Single session: adapter handles authorize internally, then signs+sends in one wallet prompt.
            // Two sessions would leave the blockhash stale (150 slots ≈ 60 s) by the second prompt.
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

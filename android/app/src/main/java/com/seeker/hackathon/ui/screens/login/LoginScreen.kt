package com.seeker.hackathon.ui.screens.login

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import com.seeker.hackathon.ui.LocalActivityResultSender

@Composable
fun LoginScreen(
    onLoginSuccess: () -> Unit,
    viewModel: LoginViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val activityResultSender = LocalActivityResultSender.current

    LaunchedEffect(state.isAuthenticated) {
        if (state.isAuthenticated) onLoginSuccess()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        Spacer(Modifier.height(80.dp))

        // Logo / title area
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "Seekerthon",
                fontSize = 40.sp,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center,
                lineHeight = 44.sp,
                color = MaterialTheme.colorScheme.onBackground,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                text = "Vote for the best Solana projects",
                fontSize = 16.sp,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        // Info cards
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            InfoCard(
                title = "Seeker Genesis Token required",
                body = "Only wallets holding an SGT can sign in — proving genuine Seeker ownership",
            )
            InfoCard(
                title = "Stake \$SKR for more power",
                body = "Staking \$SKR multiplies your vote weight up to 5×",
            )
            InfoCard(
                title = "USDC prize pool",
                body = "Winners receive their prize directly in USDC on-chain",
            )
        }

        // Connect wallet button
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (state.error != null) {
                Text(
                    text = state.error!!,
                    color = MaterialTheme.colorScheme.error,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                )
            }

            Button(
                onClick = { viewModel.connect(activityResultSender) },
                enabled = !state.isLoading,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
                shape = RoundedCornerShape(12.dp),
            ) {
                if (state.isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        color = MaterialTheme.colorScheme.onPrimary,
                        strokeWidth = 2.dp,
                    )
                } else {
                    Text("Connect Seeker Wallet", fontSize = 16.sp, fontWeight = FontWeight.Medium)
                }
            }

            Text(
                text = "A Seeker Genesis Token in your wallet is required to sign in",
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
private fun InfoCard(title: String, body: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(title, fontWeight = FontWeight.Medium, fontSize = 14.sp)
            Spacer(Modifier.height(4.dp))
            Text(body, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

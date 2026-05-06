package com.seeker.hackathon.ui

import androidx.compose.runtime.Composable
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.seeker.hackathon.ui.screens.feed.VotingFeedScreen
import com.seeker.hackathon.ui.screens.hackathons.HackathonListScreen
import com.seeker.hackathon.ui.screens.login.LoginScreen

object Routes {
    const val LOGIN = "login"
    const val HACKATHONS = "hackathons"
    const val VOTING_FEED = "feed/{hackathonId}"
    fun votingFeed(id: String) = "feed/$id"
}

@Composable
fun AppNavGraph() {
    val navController = rememberNavController()

    NavHost(navController = navController, startDestination = Routes.LOGIN) {

        composable(Routes.LOGIN) {
            LoginScreen(
                onLoginSuccess = {
                    navController.navigate(Routes.HACKATHONS) {
                        popUpTo(Routes.LOGIN) { inclusive = true }
                    }
                }
            )
        }

        composable(Routes.HACKATHONS) {
            HackathonListScreen(
                onHackathonClick = { id ->
                    navController.navigate(Routes.votingFeed(id))
                }
            )
        }

        composable(
            route = Routes.VOTING_FEED,
            arguments = listOf(navArgument("hackathonId") { type = NavType.StringType })
        ) { backStackEntry ->
            val hackathonId = backStackEntry.arguments?.getString("hackathonId") ?: return@composable
            VotingFeedScreen(hackathonId = hackathonId)
        }
    }
}

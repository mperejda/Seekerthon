package com.alpinelabs.seekerthon.ui

import androidx.compose.runtime.Composable
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.alpinelabs.seekerthon.ui.screens.activity.ActivityScreen
import com.alpinelabs.seekerthon.ui.screens.feed.VotingFeedScreen
import com.alpinelabs.seekerthon.ui.screens.hackathons.CreateHackathonScreen
import com.alpinelabs.seekerthon.ui.screens.hackathons.HackathonListScreen
import com.alpinelabs.seekerthon.ui.screens.login.LoginScreen

object Routes {
    const val LOGIN = "login"
    const val HACKATHONS = "hackathons"
    const val CREATE_HACKATHON = "create_hackathon"
    const val ACTIVITY = "activity"
    const val VOTING_FEED = "feed/{hackathonId}?leaderboardOnly={leaderboardOnly}"
    fun votingFeed(id: String, leaderboardOnly: Boolean = false) = "feed/$id?leaderboardOnly=$leaderboardOnly"
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
                onHackathonClick = { id, leaderboardOnly ->
                    navController.navigate(Routes.votingFeed(id, leaderboardOnly))
                },
                onSignOut = {
                    navController.navigate(Routes.LOGIN) {
                        popUpTo(Routes.HACKATHONS) { inclusive = true }
                    }
                },
                onCreateHackathon = {
                    navController.navigate(Routes.CREATE_HACKATHON)
                },
                onActivityClick = {
                    navController.navigate(Routes.ACTIVITY)
                },
            )
        }

        composable(Routes.ACTIVITY) {
            ActivityScreen(
                onBack = { navController.popBackStack() },
                onSessionExpired = {
                    navController.navigate(Routes.LOGIN) {
                        popUpTo(0) { inclusive = true }
                    }
                },
            )
        }

        composable(Routes.CREATE_HACKATHON) {
            CreateHackathonScreen(onBack = { navController.popBackStack() })
        }

        composable(
            route = Routes.VOTING_FEED,
            arguments = listOf(
                navArgument("hackathonId") { type = NavType.StringType },
                navArgument("leaderboardOnly") {
                    type = NavType.BoolType
                    defaultValue = false
                },
            )
        ) { backStackEntry ->
            val hackathonId = backStackEntry.arguments?.getString("hackathonId") ?: return@composable
            VotingFeedScreen(hackathonId = hackathonId)
        }
    }
}

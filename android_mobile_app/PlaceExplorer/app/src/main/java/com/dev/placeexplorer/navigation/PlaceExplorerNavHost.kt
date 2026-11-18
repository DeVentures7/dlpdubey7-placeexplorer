package com.dev.placeexplorer.navigation

import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import androidx.compose.runtime.Composable
import com.dev.placeexplorer.presentation.home.HomeScreen
import com.dev.placeexplorer.presentation.itinerary.ItineraryScreen
import com.dev.placeexplorer.presentation.details.PlaceDetailsScreen

/**
 * Route names used across the app.
 *
 * Place IDs come from the backend as "node/123" / "way/456" — the slash
 * must be URL-encoded inside the route argument, otherwise the route
 * pattern "place_details/{placeId}" does not match and navigation
 * crashes with IllegalArgumentException.
 */
object Routes {
    const val HOME = "home"
    const val ITINERARY = "itinerary"
    const val PLACE_DETAILS = "place_details/{placeId}"

    fun placeDetails(placeId: String): String {
        val encoded = java.net.URLEncoder.encode(placeId, "UTF-8")
        return "place_details/$encoded"
    }
}

@Composable
fun PlaceExplorerNavHost(navController: NavHostController) {
    NavHost(
        navController = navController,
        startDestination = Routes.HOME
    ) {
        composable(Routes.HOME) {
            HomeScreen(
                onOutingGenerated = {
                    navController.navigate(Routes.ITINERARY) {
                        // Avoid stacking a new itinerary screen on every generation.
                        popUpTo(Routes.HOME) { saveState = true }
                        launchSingleTop = true
                        restoreState = true
                    }
                }
            )
        }
        composable(Routes.ITINERARY) {
            ItineraryScreen(
                onBack = { navController.popBackStack() },
                onPlaceSelected = { placeId -> navController.navigate(Routes.placeDetails(placeId)) }
            )
        }
        composable(
            route = Routes.PLACE_DETAILS,
            arguments = listOf(navArgument("placeId") { type = NavType.StringType })
        ) { entry ->
            PlaceDetailsScreen(
                placeId = entry.arguments
                    ?.getString("placeId")
                    ?.let { java.net.URLDecoder.decode(it, "UTF-8") }
                    .orEmpty(),
                onBack = { navController.popBackStack() }
            )
        }
    }
}

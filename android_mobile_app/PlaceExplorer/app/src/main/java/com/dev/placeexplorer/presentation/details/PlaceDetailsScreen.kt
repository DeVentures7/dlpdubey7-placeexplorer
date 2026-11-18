package com.dev.placeexplorer.presentation.details

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Directions
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.dev.placeexplorer.core.AppContainer
import com.dev.placeexplorer.core.OutingSession
import com.dev.placeexplorer.domain.model.Place
import com.dev.placeexplorer.presentation.components.ErrorDialog
import com.dev.placeexplorer.presentation.components.InfoRow
import com.dev.placeexplorer.presentation.itinerary.distanceLabel
import com.dev.placeexplorer.presentation.itinerary.formatDuration
import com.dev.placeexplorer.ui.theme.PlaceExplorerTheme

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaceDetailsScreen(
    placeId: String,
    onBack: () -> Unit,
    viewModel: PlaceDetailsViewModel = placeDetailsViewModel(placeId)
) {
    val uiState by viewModel.uiState.collectAsState()

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                }
            },
            windowInsets = WindowInsets.statusBars,
            colors = TopAppBarDefaults.topAppBarColors(
                containerColor = Color.Transparent
            )
        )

        when {
            // No seeded place at all: the id came from somewhere the
            // session does not know (process death). Keep the honest state.
            uiState.place == null -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        "Place not found",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            else -> {
                PlaceDetailsContent(uiState = uiState)
            }
        }
    }

    uiState.error?.let { error ->
        ErrorDialog(
            message = error,
            onDismiss = viewModel::dismissError
        )
    }
}

@Composable
private fun PlaceDetailsContent(uiState: PlaceDetailsUiState) {
    val place = uiState.place!!
    val context = LocalContext.current
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(bottom = 32.dp)
    ) {
        // ---- Hero section ----
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(180.dp)
                .background(
                    Brush.linearGradient(
                        listOf(
                            MaterialTheme.colorScheme.primary,
                            MaterialTheme.colorScheme.secondary
                        )
                    )
                )
        ) {
            // Image placeholder
            Surface(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(20.dp)
                    .size(width = 72.dp, height = 72.dp),
                shape = RoundedCornerShape(16.dp),
                color = Color.White.copy(alpha = 0.25f)
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("🖼️", style = MaterialTheme.typography.headlineMedium)
                }
            }
            Column(
                Modifier
                    .align(Alignment.BottomStart)
                    .padding(start = 104.dp, bottom = 20.dp)
            ) {
                Text(
                    text = place.name,
                    style = MaterialTheme.typography.headlineSmall,
                    color = Color.White
                )
                Text(
                    text = distanceLabel(place.latitude, place.longitude, uiState.userLocation) +
                        " from your location",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.White.copy(alpha = 0.9f)
                )
            }
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Spacer(Modifier.height(16.dp))

            // ---- Description (brief) ----
            Text(
                text = place.shortDescription.ifBlank { place.fullDescription },
                style = MaterialTheme.typography.bodyLarge,
                maxLines = 3
            )

            // ---- Key facts card ----
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = MaterialTheme.colorScheme.surface,
                border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))
            ) {
                Column(
                    Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    InfoRow(
                        icon = Icons.Default.LocationOn,
                        text = place.address
                    )
                    if (place.openingHours.isNotBlank()) {
                        InfoRow(
                            icon = Icons.Default.Schedule,
                            text = "Opening hours: ${place.openingHours}"
                        )
                    }
                    InfoRow(
                        icon = Icons.Default.Place,
                        text = "Suggested visit: ${formatDuration(place.suggestedVisitMinutes)}"
                    )
                }
            }

            // ---- Navigate action: opens directions in a maps app ----
            Button(
                onClick = { openNavigation(context, place) },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp),
                shape = RoundedCornerShape(14.dp)
            ) {
                Icon(Icons.Default.Directions, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Navigate")
            }

            // ---- Nearby food options ----
            // Loaded independently in the background; only this section
            // shows a lightweight spinner while it works.
            Text(
                "Nearby food options",
                style = MaterialTheme.typography.titleMedium
            )
            when {
                uiState.isFoodLoading -> {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 12.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.width(18.dp).height(18.dp),
                            strokeWidth = 2.dp
                        )
                        Spacer(Modifier.width(10.dp))
                        Text(
                            "Finding nearby food options…",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                uiState.nearbyRestaurants.isEmpty() -> {
                    Text(
                        "No nearby food options found.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                else -> {
                    uiState.nearbyRestaurants.forEach { rec ->
                        Surface(
                            shape = RoundedCornerShape(12.dp),
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                        ) {
                            Row(
                                Modifier.padding(12.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Icon(
                                    Icons.Default.Restaurant,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.tertiary
                                )
                                Spacer(Modifier.width(10.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(rec.name, style = MaterialTheme.typography.titleMedium)
                                    Text(
                                        foodDistanceLabel(rec.distanceKm),
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                                if (rec.isVegetarianFriendly) {
                                    Surface(
                                        shape = RoundedCornerShape(50),
                                        color = MaterialTheme.colorScheme.tertiaryContainer
                                    ) {
                                        Text(
                                            "🟢 Veg",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onTertiaryContainer,
                                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/** "450 m away" under 1 km, "2.5 km away" otherwise. */
private fun foodDistanceLabel(distanceKm: Double): String =
    if (distanceKm < 1.0) "${Math.round(distanceKm * 1000)} m away"
    else "%.1f km away".format(distanceKm)

/**
 * Opens walking/turn-by-turn directions to the place in an external maps
 * app. When no maps app handles geo: URIs, the request simply does
 * nothing - the rest of the details screen keeps working.
 */
private fun openNavigation(
    context: android.content.Context,
    place: Place
) {
    val uri = Uri.parse(
        "google.navigation:q=${place.latitude},${place.longitude}"
    )
    val intent = Intent(Intent.ACTION_VIEW, uri).apply {
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    runCatching { context.startActivity(intent) }
}

/** Factory so the ViewModel can receive the navigation argument. */
@Composable
private fun placeDetailsViewModel(placeId: String): PlaceDetailsViewModel {
    val factory = viewModelFactory {
        initializer {
            PlaceDetailsViewModel(
                placeId = placeId,
                locationProvider = AppContainer.locationProviderOrNull()
            )
        }
    }
    return viewModel(factory = factory)
}

@Preview(showBackground = true, showSystemUi = true)
@Composable
private fun PlaceDetailsScreenPreview() {
    PlaceExplorerTheme {
        PlaceDetailsScreen(placeId = "node/123", onBack = {})
    }
}

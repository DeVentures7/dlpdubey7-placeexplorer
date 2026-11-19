package com.dev.placeexplorer.presentation.home

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.dev.placeexplorer.domain.model.FoodPreference
import com.dev.placeexplorer.domain.model.Interest
import com.dev.placeexplorer.domain.model.OutingDuration
import com.dev.placeexplorer.domain.model.TimeOfDay
import com.dev.placeexplorer.presentation.components.BrandHeader
import com.dev.placeexplorer.presentation.components.ErrorDialog
import com.dev.placeexplorer.presentation.components.ChoicePill
import com.dev.placeexplorer.presentation.components.InterestCard
import com.dev.placeexplorer.presentation.components.SectionHeader
import com.dev.placeexplorer.ui.theme.AppBackgroundBrush
import com.dev.placeexplorer.ui.theme.PlaceExplorerTheme

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onOutingGenerated: () -> Unit,
    viewModel: HomeViewModel = viewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    // Launch the system permission dialog when the ViewModel requests it.
    val locationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        val granted = grants.values.any { it }
        viewModel.onLocationPermissionResult(granted)
    }

    androidx.compose.runtime.LaunchedEffect(uiState.needsPermissionRequest) {
        if (uiState.needsPermissionRequest) {
            locationPermissionLauncher.launch(
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION
                )
            )
        }
    }

    androidx.compose.runtime.LaunchedEffect(Unit) {
        viewModel.events.collect { event ->
            when (event) {
                HomeViewModel.Event.OutingReady -> onOutingGenerated()
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize().background(AppBackgroundBrush)
            // Keep all content below the status bar: edge-to-edge is on,
            // so the status-bar inset must be added explicitly.
            .windowInsetsPadding(WindowInsets.statusBars)
            .verticalScroll(rememberScrollState())
    ) {
        BrandHeader()

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(top = 6.dp, bottom = 12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            // ---------- Destination ----------
            SectionHeader(
                title = "Destination",
                subtitle = if (uiState.isResolvingCurrentCity) "Detecting your city…" else "Choose where to explore"
            )
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = MaterialTheme.colorScheme.surface,
                border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        imageVector = Icons.Default.LocationOn,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary
                    )
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            // No detected city yet: prompt instead of a guess.
                            text = uiState.destination.ifBlank { "Select Destination" },
                            style = MaterialTheme.typography.titleMedium,
                            color = if (uiState.destination.isBlank()) {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            } else {
                                MaterialTheme.colorScheme.onSurface
                            }
                        )
                        Text(
                            text = when {
                                uiState.destination.isNotBlank() && uiState.currentLocationFix != null ->
                                    "Starting from your current location"
                                uiState.destination.isNotBlank() ->
                                    "Starting from the destination city center"
                                uiState.isLocating || uiState.isResolvingCurrentCity ->
                                    "Locating you…"
                                else ->
                                    "Select your destination to continue"
                            },
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.tertiary
                        )
                    }
                    Surface(
                        shape = RoundedCornerShape(50),
                        color = MaterialTheme.colorScheme.tertiaryContainer,
                        onClick = viewModel::onChangeDestinationClicked
                    ) {
                        Row(
                            Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "Change",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onTertiaryContainer
                            )
                            Icon(
                                imageVector = Icons.Default.ExpandMore,
                                contentDescription = null,
                                modifier = Modifier.width(14.dp),
                                tint = MaterialTheme.colorScheme.onTertiaryContainer
                            )
                        }
                    }
                }
            }

            // ---------- Destination search (opened by Change) ----------
            if (uiState.isDestinationSearchActive) {
                Surface(
                    shape = RoundedCornerShape(14.dp),
                    color = MaterialTheme.colorScheme.surface,
                    border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))
                ) {
                    Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedTextField(
                            value = uiState.destinationSearchQuery,
                            onValueChange = viewModel::onDestinationSearchQueryChanged,
                            placeholder = { Text("Search cities,areas or landmarks") },
                            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                            trailingIcon = {
                                if (uiState.isSearchingDestination) {
                                    CircularProgressIndicator(modifier = Modifier.width(18.dp).height(18.dp), strokeWidth = 2.dp)
                                }
                            },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth()
                        )
                        uiState.destinationSearchResults.forEach { result ->
                            Surface(
                                shape = RoundedCornerShape(10.dp),
                                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                onClick = { viewModel.onDestinationSelected(result) }
                            ) {
                                Column(Modifier.padding(12.dp)) {
                                    Text(result.name, style = MaterialTheme.typography.bodyLarge)
                                    Text(
                                        result.address,
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 1
                                    )
                                }
                            }
                        }
                        if (!uiState.isSearchingDestination &&
                            uiState.destinationSearchQuery.length >= 3 &&
                            uiState.destinationSearchResults.isEmpty()
                        ) {
                            Text(
                                text = "No matches found. Try a different city or landmark.",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Text(
                            text = "Cancel",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.clickable { viewModel.onDestinationSearchDismissed() }
                        )
                    }
                }
            }

            // ---------- Duration & time ----------
            Row(
                modifier = Modifier.padding(top = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(25.dp)
            ) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    SectionHeader("Outing Duration")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutingDuration.entries.forEach { duration ->
                            ChoicePill(
                                label = duration.label,
                                selected = uiState.duration == duration,
                                onClick = { viewModel.onDurationSelected(duration) }
                            )
                        }
                    }
                }
            }

            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                SectionHeader("Outing Time")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TimeOfDay.entries.forEach { time ->
                        ChoicePill(
                            label = time.label,
                            selected = uiState.timeOfDay == time,
                            onClick = { viewModel.onTimeOfDaySelected(time) }
                        )
                    }
                }
            }

            // ---------- Interests ----------
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                SectionHeader(
                    title = "Interests",
                    subtitle = "Pick one theme for your outing"
                )
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Interest.entries.chunked(2).forEach { rowItems ->
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            rowItems.forEach { interest ->
                                InterestCard(
                                    emoji = interest.emoji,
                                    title = interest.label,
                                    selected = interest in uiState.interests,
                                    onClick = { viewModel.onInterestToggled(interest) },
                                    modifier = Modifier.weight(1f)
                                )
                            }
                            if (rowItems.size == 1) Spacer(Modifier.weight(1f))
                        }
                    }
                }
            }

            // ---------- Food ----------
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                SectionHeader("Food")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FoodPreference.entries.forEach { pref ->
                        ChoicePill(
                            label = pref.label,
                            selected = uiState.foodPreference == pref,
                            onClick = { viewModel.onFoodPreferenceSelected(pref) }
                        )
                    }
                }
            }

            // ---------- Generate ----------
            // Loading state lives INSIDE the button only: spinner plus
            // "Planning Your Outing..." replaces the label while the
            // itinerary is generated; the button returns to normal on
            // success or failure.
            Button(
                onClick = { viewModel.generateOuting() },
                enabled = !uiState.isGenerating && !uiState.isLocating,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp, bottom = 24.dp)
                    .height(56.dp),
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                    disabledContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.45f),
                    disabledContentColor = MaterialTheme.colorScheme.onPrimary
                )
            ) {
                if (uiState.isGenerating) {
                    CircularProgressIndicator(
                        modifier = Modifier.width(22.dp).height(22.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary
                    )
                    Spacer(Modifier.width(12.dp))
                    Text(
                        "Planning Your Outing...",
                        style = MaterialTheme.typography.titleMedium
                    )
                } else {
                    Text("Plan My Outing", style = MaterialTheme.typography.titleMedium)
                }
            }

            // Errors surface as a popup dialog with a cross button to
            // dismiss and Try Again to re-run what failed.
            uiState.error?.let { error ->
                ErrorDialog(
                    message = error,
                    onDismiss = viewModel::dismissError,
                    onRetry = {
                        viewModel.dismissError()
                        viewModel.generateOuting()
                    }
                )
            }

            // Location problems (permission denied, GPS off, no fix) get
            // the same dialog treatment; Try Again re-attempts the fix.
            uiState.locationError?.let { locationError ->
                ErrorDialog(
                    message = locationError,
                    onDismiss = viewModel::dismissLocationError,
                    onRetry = {
                        viewModel.dismissLocationError()
                        viewModel.onUseCurrentLocationAgain()
                    }
                )
            }
        }
    }
}

@Preview(showBackground = true, showSystemUi = true)
@Composable
private fun HomeScreenPreview() {
    PlaceExplorerTheme {
        HomeScreen(onOutingGenerated = {})
    }
}

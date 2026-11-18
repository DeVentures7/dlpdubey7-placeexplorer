package com.dev.placeexplorer.data.mock

import com.dev.placeexplorer.domain.model.Interest
import com.dev.placeexplorer.domain.model.MealType
import com.dev.placeexplorer.domain.model.NearbyFoodRecommendation
import com.dev.placeexplorer.domain.model.Place

/**
 * Sample Pune places and food spots for the mock repository.
 *
 * Coordinates are approximate real-world locations so that, once Google
 * Maps is integrated, the itinerary ordering is actually geographically
 * sensible.
 */
object PunePlaces {

    val shaniwarWada = Place(
        id = "shaniwar-wada",
        name = "Shaniwar Wada",
        shortDescription = "Historic Peshwa palace fort in the heart of Pune",
        fullDescription = "Built in 1732 as the seat of the Peshwa rulers of the Maratha Empire, " +
            "Shaniwar Wada is now a ruin whose towering teak gate and surviving walls tell " +
            "stories of Maratha glory. The evening light-and-sound show narrates its history. " +
            "Its central location makes it a natural first or last stop in any Pune outing.",
        address = "Shaniwar Peth, Pune, Maharashtra 411030",
        latitude = 18.5195,
        longitude = 73.8553,
        interests = setOf(Interest.HERITAGE),
        suggestedVisitMinutes = 60,
        openingHours = "8:00 AM – 6:30 PM"
    )

    val dagdusheth = Place(
        id = "dagdusheth-ganpati",
        name = "Dagdusheth Halwai Ganpati Temple",
        shortDescription = "Pune's most beloved Ganesha temple, richly ornamented",
        fullDescription = "The Shreemant Dagdusheth Halwai Sarvajanik Ganpati is one of the " +
            "richest and most famous Ganesha temples in India, visited by lakhs of devotees " +
            "during Ganesh Chaturthi. The idol is adorned with gold jewellery and the temple " +
            "glows with lamps in the evening. Located close to Shaniwar Wada and the bustling " +
            "Laxmi Road shopping area.",
        address = "Ganpati Peth, Pune, Maharashtra 411011",
        latitude = 18.5204,
        longitude = 73.8567,
        interests = setOf(Interest.TEMPLES),
        suggestedVisitMinutes = 45,
        openingHours = "6:00 AM – 10:00 PM"
    )

    val SarasBaag = Place(
        id = "saras-baag",
        name = "Saras Baug",
        shortDescription = "Lake garden with the Siddhivinayak temple at its centre",
        fullDescription = "Saras Baug is a sprawling garden built around a lake, with the " +
            "Sarasbaug Siddhivinayak temple on a small hillock at its centre. Popular with " +
            "families for morning walks, boating and street snacks, it combines nature, " +
            "spirituality and local flavour in one stop.",
        address = "Saras Baug, Pune, Maharashtra 411030",
        latitude = 18.4886,
        longitude = 73.8556,
        interests = setOf(Interest.NATURE, Interest.TEMPLES),
        suggestedVisitMinutes = 50,
        openingHours = "6:00 AM – 9:00 PM"
    )

    val parvatiHill = Place(
        id = "parvati-hill",
        name = "Parvati Hill Temple",
        shortDescription = "Hilltop temple complex with panoramic city views",
        fullDescription = "A climb of 103 steps leads to the Parvati temple complex, the " +
            "oldest heritage structure in Pune, perched on a hill in the middle of the city. " +
            "The viewpoint offers a sweeping panorama of Pune, especially beautiful at sunset. " +
            "The complex includes the Peshwa museum and several small shrines.",
        address = "Parvati Paytha, Pune, Maharashtra 411009",
        latitude = 18.4836,
        longitude = 73.8392,
        interests = setOf(Interest.TEMPLES, Interest.NATURE, Interest.HERITAGE),
        suggestedVisitMinutes = 60,
        openingHours = "6:00 AM – 8:00 PM"
    )

    val pataleshwar = Place(
        id = "pataleshwar-cave-temple",
        name = "Pataleshwar Cave Temple",
        shortDescription = "8th-century rock-cut temple carved out of a single basalt rock",
        fullDescription = "Dating to the 8th century Rashtrakuta era, this monolithic " +
            "rock-cut temple dedicated to Pataleshwar (Shiva) sits quietly amid old trees in " +
            "the middle of the city. The circular Nandi mandapa carved from a single stone is " +
            "the highlight. A calm, shaded stop that contrasts with Pune's busy streets.",
        address = "Jangali Maharaj Road, Shivajinagar, Pune 411005",
        latitude = 18.5266,
        longitude = 73.8400,
        interests = setOf(Interest.TEMPLES, Interest.HERITAGE),
        suggestedVisitMinutes = 40,
        openingHours = "7:00 AM – 8:30 PM"
    )

    val agaKhanPalace = Place(
        id = "aga-khan-palace",
        name = "Aga Khan Palace",
        shortDescription = "Grand palace where Mahatma Gandhi was imprisoned; memorial to Kasturba Gandhi",
        fullDescription = "Built in 1892 by Sultan Muhammed Shah Aga Khan III, this Italianate " +
            "palace is where Mahatma Gandhi, Kasturba Gandhi and Mahadev Desai were imprisoned " +
            "during the Quit India Movement. It now houses a Gandhi memorial museum and the " +
            "samadhis of Kasturba and Mahadev Desai in its serene gardens.",
        address = "Kalyani Nagar, Pune, Maharashtra 411006",
        latitude = 18.5525,
        longitude = 73.8896,
        interests = setOf(Interest.HERITAGE),
        suggestedVisitMinutes = 75,
        openingHours = "9:00 AM – 5:30 PM"
    )

    val oshoGarden = Place(
        id = "osho-teerth-park",
        name = "Osho Teerth Park",
        shortDescription = "Tranquil Japanese-style garden with streams and bamboo groves",
        fullDescription = "A beautifully landscaped garden transformed from a barren ravine " +
            "into a Japanese-style meditation park with streams, stone pathways, bamboo " +
            "groves and thousands of flowers. A peaceful walk of 30-45 minutes, located near " +
            "Koregaon Park's famous cafes and shopping streets.",
        address = "17, Koregaon Park, Pune, Maharashtra 411001",
        latitude = 18.5362,
        longitude = 73.8939,
        interests = setOf(Interest.NATURE),
        suggestedVisitMinutes = 40,
        openingHours = "6:00 AM – 9:00 AM, 3:00 PM – 6:00 PM"
    )

    val korumMall = Place(
        id = "korum-mall",
        name = "Korum Mall",
        shortDescription = "Large mall with shops, food court and multiplex",
        fullDescription = "One of Pune's largest shopping malls, with national and " +
            "international brands, a multiplex and a large food court. A good evening stop " +
            "for shopping and entertainment, especially convenient to combine with a visit " +
            "to Parvati Hill and Saras Baug.",
        address = "Mangaldas Road, Sangamvadi, Pune 411001",
        latitude = 18.5300,
        longitude = 73.8740,
        interests = setOf(Interest.SHOPPING),
        suggestedVisitMinutes = 90,
        openingHours = "11:00 AM – 10:00 PM"
    )

    val fcRoad = Place(
        id = "fc-road",
        name = "Fergusson College Road (FC Road)",
        shortDescription = "Iconic street for street shopping, cafes and college vibe",
        fullDescription = "FC Road is Pune's classic hangout street: book stores, street " +
            "shopping, famous snacks at Vaishali and Roopali, and the youthful energy of " +
            "the college crowd. Best in the evening, easily combined with a visit to the " +
            "nearby Pataleshwar temple or Shimla Office chowk area.",
        address = "Fergusson College Road, Shivajinagar, Pune 411005",
        latitude = 18.5210,
        longitude = 73.8397,
        interests = setOf(Interest.SHOPPING),
        suggestedVisitMinutes = 60,
        openingHours = "10:00 AM – 10:30 PM"
    )

    val phulrani = Place(
        id = "phulrani-hill",
        name = "Phulrani Hill",
        shortDescription = "Quiet hill garden with city views, near Parvati",
        fullDescription = "A lesser-known hill garden with walking tracks, flower beds and " +
            "a small viewpoint over the city. An alternative to the busier Parvati Hill for " +
            "those who prefer a quiet nature stop.",
        address = "Bibwewadi Road, Pune, Maharashtra 411037",
        latitude = 18.4770,
        longitude = 73.8480,
        interests = setOf(Interest.NATURE),
        suggestedVisitMinutes = 40,
        openingHours = "6:00 AM – 9:00 PM"
    )

    val empressGarden = Place(
        name = "Empress Garden",
        id = "empress-garden",
        shortDescription = "Botanical garden with old trees, lawns and a small train",
        fullDescription = "A 39-acre botanical garden near Pune Cantonment with century-old " +
            "trees, flower shows, a small toy train and play areas. A relaxed green stop " +
            "that pairs well with the Aga Khan Palace, just a short drive away.",
        address = "Empress Botanical Garden, Pune Cantonment, Pune 411001",
        latitude = 18.5390,
        longitude = 73.8790,
        interests = setOf(Interest.NATURE),
        suggestedVisitMinutes = 50,
        openingHours = "8:00 AM – 6:30 PM"
    )

    val all = listOf(
        shaniwarWada, dagdusheth, SarasBaag, parvatiHill, pataleshwar, agaKhanPalace,
        oshoGarden, korumMall, fcRoad, phulrani, empressGarden
    )

    val byId: Map<String, Place> = all.associateBy { it.id }

    val breakfastSpots = listOf(
        NearbyFoodRecommendation(
            name = "Vaishali",
            cuisine = "South Indian",
            mealType = MealType.BREAKFAST,
            isVegetarianFriendly = true,
            distanceKm = 0.4,
            priceLevel = 2
        ),
        NearbyFoodRecommendation(
            name = "Roopali",
            cuisine = "South Indian",
            mealType = MealType.BREAKFAST,
            isVegetarianFriendly = true,
            distanceKm = 0.6,
            priceLevel = 2
        ),
        NearbyFoodRecommendation(
            name = "Chitale Bandhu Mithaiwale",
            cuisine = "Sweets & Snacks",
            mealType = MealType.SNACK,
            isVegetarianFriendly = true,
            distanceKm = 0.3,
            priceLevel = 2
        ),
        NearbyFoodRecommendation(
            name = "German Bakery Wunderbar",
            cuisine = "Continental",
            mealType = MealType.BREAKFAST,
            isVegetarianFriendly = true,
            distanceKm = 1.2,
            priceLevel = 3
        )
    )

    val lunchSpots = listOf(
        NearbyFoodRecommendation(
            name = "Shabree",
            cuisine = "Maharashtrian Thali",
            mealType = MealType.LUNCH,
            isVegetarianFriendly = true,
            distanceKm = 0.5,
            priceLevel = 2
        ),
        NearbyFoodRecommendation(
            name = "Durvankur",
            cuisine = "Maharashtrian Thali",
            mealType = MealType.LUNCH,
            isVegetarianFriendly = true,
            distanceKm = 0.8,
            priceLevel = 2
        ),
        NearbyFoodRecommendation(
            name = "Barbeque Nation",
            cuisine = "Grill & Buffet",
            mealType = MealType.LUNCH,
            isVegetarianFriendly = false,
            distanceKm = 1.5,
            priceLevel = 3
        )
    )

    val snackSpots = listOf(
        NearbyFoodRecommendation(
            name = "Sujata Mastani",
            cuisine = "Desserts & Mastani",
            mealType = MealType.SNACK,
            isVegetarianFriendly = true,
            distanceKm = 0.2,
            priceLevel = 1
        ),
        NearbyFoodRecommendation(
            name = "Badshahi Chap",
            cuisine = "Kebabs",
            mealType = MealType.SNACK,
            isVegetarianFriendly = false,
            distanceKm = 0.9,
            priceLevel = 2
        )
    )
}

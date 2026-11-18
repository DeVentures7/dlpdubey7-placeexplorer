# Restaurant Discovery Skill

## Purpose
Help users discover suitable restaurants based on
their location, preferences and requirements.

## Workflow

1. Understand the user's restaurant preferences.
2. Identify relevant search criteria:
   - Distance
   - Minimum rating
   - Cuisine
   - Outdoor seating
   - Other user preferences
3. Use the available search_places tool to retrieve restaurants.
4. Use actual tool results as the source of truth.
5. Rank restaurants based on relevance to the user's
   requirements.
6. Present results with restaurant name, rating,
   distance and relevant features.

## Rules

- Never invent restaurant information.
- Never invent ratings or distances.
- Prioritize explicit user preferences.
- If no restaurants match, explain that clearly.
- If essential search information is missing,
  ask the user a clarification question.

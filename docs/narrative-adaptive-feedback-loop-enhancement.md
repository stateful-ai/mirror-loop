## Doc: Adaptive Feedback Loop Enhancement

### Voice & tone
The voice and tone of Mirror Loop should be observant, slightly mysterious, and ever-so-slightly omniscient. It should make the player feel seen and understood, yet leave enough ambiguity to encourage exploration and experimentation. Sample line: "Your steps hint at a preference for the unknown."

### Authored content
The authored content will include a series of pre-scripted observations and reflections tailored to common player actions. These will serve as the foundation for the game's adaptive narrative, ensuring consistency and reliability in the feedback provided to the player.

Sample authored lines:
- "Your steps hint at a preference for the unknown."
- "You seem drawn to the unseen corners."
- "There’s a subtle pull towards the light."

### Dynamic moments
- **Moment:** Adaptive Observation Generation
  - **What gets generated:** Observational sentences that reflect the player's actions beyond the scripted scenarios.
  - **Structured shape returned:** 
    ```json
    {
      "observation": "string",
      "visual_feedback": "string"
    }
    ```
  - **Fallback when generation fails or is too slow:** Use a generic but contextually relevant observation such as "Your path is clear" paired with a default visual feedback like a slight shift in ambient lighting.
  - **Token budget:** 20 tokens for the observation, 10 tokens for the visual feedback.

## Doc: First Beat of Axis Recognition in Mirror Loop

### Core loop
The core loop revolves around the player performing actions which the game recognizes and reflects back through text and visual feedback, creating an interactive experience where players can experiment with different behaviors. The fun hypothesis is that the game's recognition and reflection of player actions create a sense of discovery and engagement, encouraging players to continue exploring and interacting with the game environment.

### Vertical slice
For this vertical slice, the player will move their character left and right within a confined space. The game will recognize this movement and provide immediate feedback, including text and visual responses. The slice is designed to be completed within a weekend, focusing on the initial interaction between the player and the game.

### Mechanics
- **Trigger Condition:** The player moves the character from the center position to either the left or right boundary of the screen. Repeated movements in the same direction will trigger additional feedback.
- **Reflection Text Shape:** A small, floating text box appears near the character, displaying a short, observational sentence like "You moved to the edge." If the player repeats the movement, the text evolves to something like "You prefer the left side," indicating a pattern of behavior.
- **Visual Response:** The background subtly shifts color to reflect the direction of movement (cool tones for left, warm tones for right). If the player continues to move in the same direction, the background color deepens, indicating a stronger connection to that direction. This change is deterministic based on the direction chosen by the player.

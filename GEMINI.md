# Veo Generators

This directory is dedicated to prompt engineering for video generation models, specifically focusing on Google Veo. It contains a collection of carefully crafted prompts, storyboard structures, and the resulting generated videos.

## Directory Overview

The project explores different cinematic styles and structural approaches to video prompting. It includes standard text-based prompts as well as more complex, JSON-structured storyboards designed to maintain character and action consistency across scenes.

## Key Files and Folders

### `prompts/`
This folder contains the core prompt engineering work.
- **`starter-prompt.md`**: A basic screenplay-style prompt involving two characters and a split-screen transition.
- **`anderson-prompt.md`**: An adaptation of the starter prompt into a Wes Anderson aesthetic (symmetry, pastel colors, whimsical tone).
- **`anderson-json-prompt.md`**: A highly structured JSON version of the Anderson prompt, defining metadata, characters, and a scene-by-scene storyboard for better model adherence.
- **`kubrick-prompt.md`**: A Kubrick-inspired version of the prompt.
- **`screenplay-critic.md`**: A meta-prompt designed to critique and improve other screenplay prompts, focusing on continuity and transitions.

### `outputs/`
Contains the generated video files (`.mp4`) resulting from the prompts.
- `anderson.mp4` / `anderson-json.mp4`: Videos generated using the Anderson-themed prompts.
- `kubrick.mp4` / `kubrick-starter.mp4`: Videos generated using the Kubrick-themed prompts.

## Usage

1. **Prompt Iteration**: Use `screenplay-critic.md` to refine new prompts before generation.
2. **Generation**: Copy the content of a prompt file (like `anderson-json-prompt.md`) into the video generation model's interface.
3. **Consistency**: Reference the JSON structures in `anderson-json-prompt.md` as a template for maintaining character and setting consistency in multi-scene videos.

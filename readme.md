# Veo Generators: Consistent Video Prompting

This repository contains a collection of prompts designed for Google Veo (via Vertex AI Studio) to create consistent
video content. While these examples are framed as infomercials for a dating app, the structures and workflows can be
adapted for any purpose requiring high consistency across scenes and characters.

## Purpose & Usage

The primary goal of this project is to explore techniques for maintaining character, location, and action consistency in
AI-generated videos. This includes:

- **Single Scene Consistency**: Ensuring the style and characters remain stable within a shot.
- **Multi-Scene Consistency**: Using structured prompts and JSON storyboards to bridge transitions between scenes
  without losing visual identity. (Coming up)

## My Workflow

The prompts in this repo reflect an iterative journey of optimization:

1.  **Initial Step**: Started with the `provided-prompt.md`, which established the basic split-screen concept.
2.  **Optimization**: Created `starter-prompt.md` to refine the language and structure for better model adherence.
3.  **Advanced Workflow**: Implemented a 2-step **Screenplay Critic** workflow. I used `screenplay-critic.md` to analyze
    and critique the prompts for character, location, and action consistency before generating the final refined prompts
    (e.g., the Anderson and Kubrick variants).
4.  **Generation & Selection**: Each prompt was run through **Vertex AI Studio**, generating 2-4 samples. The videos in
    the `outputs/` folder represent the best result from those samples.
    - _Note: Music was not prompted so you can ignore that._

## Chronology

Below is the progression of prompts and their corresponding video outputs:

| Phase                  | Prompt File                                                        | Output Video                                           | Description                                                                                                                                                                                                   |
| :--------------------- | :----------------------------------------------------------------- | :----------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Baseline**           | [provided-prompt.md](prompts/provided-prompt.md)                   | -                                                      | Initial split-screen concept.                                                                                                                                                                                 |
| **Iterated**           | [starter-prompt.md](prompts/starter-prompt.md)                     | [kubrick-starter.mp4](outputs/kubrick-starter.mp4)     | Optimized structure with a specific director style.                                                                                                                                                           |
| **Refined (Kubrick)**  | [kubrick-prompt.md](prompts/kubrick-prompt.md)                     | [kubrick.mp4](outputs/kubrick.mp4)                     | High-contrast, symmetrical Kubrick aesthetic.                                                                                                                                                                 |
| **Refined (Anderson)** | [anderson-prompt.md](prompts/anderson-prompt.md)                   | [anderson.mp4](outputs/anderson.mp4)                   | Whimsical, pastel Wes Anderson aesthetic.                                                                                                                                                                     |
| **Structured (JSON)**  | [anderson-json-prompt.md](prompts/anderson-json-prompt.md)         | [anderson-json.mp4](outputs/anderson-json.mp4)         | Using JSON storyboard for maximum consistency. _Note: Although it doesn't affect the outcome, JSON provides an opportunity to create more structured prompts (it's a matter of preference, not a necessity)._ |
| **9:16 Aspect Ratio**  | [anderson-json-916-prompt.md](prompts/anderson-json-916-prompt.md) | [anderson-json-916.mp4](outputs/anderson-json-916.mp4) | 9:16 variant using the same structured approach.                                                                                                                                                              |

## Workflow Tools

- **[screenplay-critic.md](prompts/screenplay-critic.md)**: Use this to review any new prompt. It focuses on continuity,
  transitions, and character consistency.

<!-- house-style: template — fill this file in, then delete this line -->

---
name: repo
description: One line that says what this does.
colors:
  primary: "#2b3a55"
  neutral-bg: "#faf7f2"
typography:
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "32px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
rounded:
  md: "8px"
spacing:
  sm: "8px"
  md: "16px"
---

# Design System: repo

<!--
  A stub. Fill it in when the project has a visual system, or delete the
  file if it does not have one — a project with no interface does not need
  a design document, and an empty one is worse than none.

  The frontmatter is normative: it is the machine-readable token layer that
  tools consume. The prose explains how to apply the tokens. When they
  disagree, the frontmatter is right.

  Keep the eight sections in this order. Omit the ones that do not apply.
-->

## Overview

**Creative North Star: "[a named metaphor]"**

<!--
  Two or three paragraphs: the personality, the density, the aesthetic
  philosophy. Start from the north star and work outward. State the
  confirmed rejections. End with a short key-characteristics list.
-->

## Colors

<!--
  Group by role, not by hue. Primary, secondary, tertiary, neutral — and
  name the colours rather than listing hex codes in prose, because the
  frontmatter already carries the values.
-->

### Primary

- **[Descriptive name]** (`#2b3a55`): where and why it is used.

### Neutral

- **[Descriptive name]** (`#faf7f2`): the ground.

### Named Rules

**The [Rule Name] Rule.** A short, memorable doctrine.

## Typography

**Display Font:** [family]
**Body Font:** [family]

<!--
  The hierarchy, with the real values: display, headline, title, body,
  label. Say what each one is for and where it appears.
-->

## Layout

<!--
  The spatial model: the grid, the container, the density, the spacing
  rhythm, what changes on a narrow screen.
-->

## Elevation & Depth

<!--
  Flat, layered or lifted. If there are no shadows, say so explicitly and
  describe how depth is conveyed instead.
-->

## Shapes

<!--
  The radius strategy, the borders, the clipping, the recurring form.
-->

## Components

<!--
  For each component: a character line, then the shape, the colour
  assignment, the states, and anything distinctive about its behaviour.
-->

### Buttons

- **Shape:** [radius, in words and in parens]
- **Primary:** [colour assignment and padding]
- **Hover / Focus:** [transitions, treatments]

### Inputs / Fields

- **Style:** [stroke, background, radius]
- **Focus:** [treatment]
- **Error / Disabled:** [if applicable]

## Do's and Don'ts

<!--
  Concrete guardrails, each one leading with "Do" or "Don't". Exact values
  only where they have been established. These are the rules a new screen
  is measured against, so write them as tests rather than as advice.
-->

### Do:

- **Do** [specific prescription].
- **Do** [specific prohibition inverted].

### Don't:

- **Don't** [specific prohibition].
- **Don't** [specific prohibition].

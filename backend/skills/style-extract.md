---
type: Procedural Skill
title: Extract a style profile from images
---
# Style extract
Read the dominant colors from the images and return a style profile: palette (2 to 8 hex colors
for chart series, most prominent first), background, surface (card color), text, accent, font_family
(a common web-safe family that looks closest, one name) and radius (corner radius in px, 0 to 32).
Use exact 6-digit hex values like #1E40AF. Keep text legible: text must contrast with background
and surface. notes: one or two plain sentences on the overall look.

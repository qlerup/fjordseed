# Nordisk surfaces and continuous voyages

The Nordisk panels use an opaque charcoal surface instead of the repeating
stone noise texture. Their backgrounds extend beneath the bronze fittings,
with no border-image outset, so there is no transparent seam around the panel.
Nested theme fieldsets use a divider rather than a second ornamental frame.
The landscape has a dark overlay so its detail stays behind the controls.

The stretched decorative oak column and the animated mist overlay have been
removed. The clearer scene is saved at
`static/nordic-saga-fjord-clear.png`. The original scene is retained. Both images
are 1672 × 941 pixels; the generated edit improves local detail but is not a
native 4K image and will still be scaled on larger screens.

The edit used the built-in imagegen tool with the original
`static/nordic-saga-fjord.png` as its edit target. Final prompt:

> Edit target: the supplied Nordic fjord background, for an existing application theme. Create a high resolution 3840x2160 landscape wallpaper version with crisp fine detail throughout. Preserve the exact scene composition, proportions, viewpoint, palette and subjects: snow-covered rocky mountain range left, turquoise aurora night sky, large calm dark fjord center, Viking longship docked at right, illuminated timber hall on upper right cliff, wooden wharf and fire at lower left. Improve clarity and fine detail, sharp natural textures in rocks, timber, ropes, snow and water. No Gaussian blur, no depth of field blur, no grain or noisy texture, no haze overlay, no oversharpening halos. Keep the center dark and quiet for application panels. No added subjects, text, frames, ornaments or UI. Intended actual image resolution 3840 by 2160 pixels.

Torrent cards are replaced during status polling. The ship crossings now use
a fixed eight-second period and a negative animation delay anchored to the page
clock. Replacing a card or changing its reported rate therefore does not reset
the ship to its entry bank. Zero transfer, pause and reduced-motion preferences
retain the stationary treatment.

Verification:

- `python tests/browser_nordic.py`: theme settings, navigation, downloads,
  dialogs and responsive layout at 1920, 1440, 900, 390 and 320 pixels.
- `python tests/browser_nordic_voyage.py`: both ships enter and leave the full
  lane, maintain direction through repeated card replacement and changing
  rates, wrap correctly and respect reduced motion.

The older `browser_seeding_progress.py` does not currently run against the
existing app: its extraction expects `function size(n)`, whereas the current
signature includes a second parameter. With the extraction adjusted temporarily,
its old upload-format assertions also fail (the app now displays precise GiB).
That unrelated test was left unchanged.

## Hanging navigation and quiet traffic

`static/nordic-navigation.js` reuses the existing settings links as a second,
smaller sign hanging below the main navigation. The main Settings link toggles
it; Escape closes it and returns focus to the link. Direct settings URLs open
it automatically. Theme switching moves the same navigation back to its normal
position for Fjord and Viking. Desktop signs sway together by 0.7 degrees in
either direction over eight seconds. Mobile, reduced motion and the animation
setting disable that sway. The submenu unfolds once when opened.

Both signs use `static/nordic-sign-oak.png`, generated with the built-in imagegen
tool. Final prompt:

> A seamless-looking realistic horizontal oak timber texture for the surface of a small hanging Viking wooden menu sign in a web app. Flat front-on close-up material photograph, wide landscape 3:1 aspect ratio. Three broad horizontal aged warm dark-brown oak planks, clear elongated wood grain, small natural knots, subtle uneven warm edges, tactile solid timber. Consistent sharp focus across all planks. Medium-dark chestnut and tobacco brown with readable grain; must visibly look like real wood even under a light dark overlay. Gentle diffuse neutral lighting, no glossy highlights, no strong lighting gradient. Fill the entire image edge to edge with wood. No text, symbols, ornamental carvings, borders, frames, metal, ropes, objects, perspective, blur or vignette.

The Nordic connection diagram now draws simple directional dashed currents.
Only routes with real transfer animate. Stationary arrowheads preserve direction
when motion is disabled. The VPN shield has no breathing animation, arrival
pulse, orbit, changing halo or rotating lights. The rate equalizers are hidden.
The original Fjord animation is preserved.

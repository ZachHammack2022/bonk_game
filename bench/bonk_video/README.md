# Matching bonk.io (a recording of the Sinking Swing)

In November 2026 the Sinking Swing was rebuilt in bonk.io's map editor and
screen-recorded (11.5 s at 60 fps), with the editor's settings:

| piece | bonk.io settings |
|---|---|
| Falling floor | free moving, density 999, bounciness 0.8, friction 0.5 (Fric Players: No), linear drag 20, spin drag 999 |
| Swing seat | two planks, free moving, density 0.3, bounciness 0, friction 0.5 (Fric Players: No), no drag |
| Rope | a rotating joint 500 up, attached to nothing, motor on: max speed 0, turn force 100 |

`measure.py` found the ball, floor, planks and rope in every frame
(`recording.json`), and `compare.py` holds our physics up against it:

    python -m bench.bonk_video.compare

| | recording | ours now | ours before |
|---|---|---|---|
| gravity | about 380-407 px/s² | 380 | 759 |
| floor sinking | 6.8 px/s | 7.0 | 7.9 |
| floor bounce | 0.8 | 0.8 | 0.4 |
| rope | 500 px, from far above the screen | 500 px | 245 px, pivot on screen |
| seat | two planks in a V, 60 x 9.5 px, leaning 10°; tilts with the rope | the same | a flat tray that stayed level |
| swing period | 7.2 s | 7.35 s | 3.6 s |
| swinging | freely, back and forth | the same, a ride slowly losing height over a minute | the same, faster |

How each was worked out:

- **Gravity.** The ball's fall after the top of its flight into the seat
  gives 407 px/s². That may include some "down" held (that's how bonk
  players pump), so it's an upper bound. The swing's period agrees
  independently: a 500 px pendulum swinging in about 7.3 s needs about 380.
  Ours is 0.75 px a step², 380 px/s² at the default speed.
- **Jumps keep their heights.** A jump's height goes with speed² / gravity,
  so jump speeds, launch pads and bumpers leave at √½ (`world.LIFT`) of the
  speeds the maps give, and the cap on going up is √½ of the speed cap
  (pogo bounces climbed until the cap stopped them). Every place you could
  reach before, you still can; you're in the air longer getting there.
- **The rope is a stiff pendulum.** bonk's rotating joint holds the seat
  rigidly to the pivot, so the seat tilts with the rope (17° of rope gave
  about 17° of tilt in the recording). Ours is a Box2D revolute joint.
- **It swings freely.** In the recording the swing eased back without
  swinging through, but that was the player steering in the seat: bonk's
  swing goes back and forth on its own once pushed. So the joint has only
  a little friction (torque 2): a ride let go 20° out still swings 7° out
  after 40 s, and an empty seat settles back in the middle. The period
  (from the ball landing to the furthest point, a quarter swing) is the
  recording's.
- **The falling floor.** Density 999 means nothing a player does moves
  it, drag 20 makes it fall at a steady speed, and spin drag 999 keeps it
  level, so a floor driven down at the same speed is the same thing (and
  the browser predicts it exactly). Friction 0.5 doesn't apply to players
  there (Fric Players: No), so ours stays slippery.

## Sliding Platform (a second recording)

Rebuilt from a bonk.io map of a wrestling ring (its decoration left out),
recorded the same way. Each half of the ring (an arm between the two ropes,
a corner block and a leaning post) is one body: free moving, density 0.01,
bounciness -999 (none), friction 0.5 (off for players), no drag, on a
springy joint (spring force 500, spring length 9999).

Tracking the ends of the arms frame by frame: run into a post and that half
slides out (200-380 px), carrying you over the edge if you keep pushing;
once you're off it, it comes home with about 500 px/s² plus 2.5/s² for each
px out (fitted to four returns, 2-3 px rms), home in about 0.75 s, and stops
against the other half. Ours (`maps.SliderMap`): halves of mass 0.06 balls
on one-way rails, pulled home by just that, sizes from the recording.

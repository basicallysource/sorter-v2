---
layout: default
title: Read what it proposes
type: tutorial
audience: operator
applies_to: Hive profile editor
section: hive
owner: hive
slug: hive-read-what-it-proposes
kicker: First profile — Read what it proposes
lede: Rules are tried top to bottom and the first match wins, so the order of the boxes is most of what a profile does. How a piece falls through the list, what the conditions mean, and a worked example of four boxes in the right order.
permalink: /hive/first-profile/read-what-it-proposes/
contributors: [brickcyclealice]
warning: >-
  **AI-generated first draft.** Rewritten on 2026-10-02 from Hive's and the sorter's source after the
  sorting profiles overhaul, not from clicking through the flow start to finish. The example's
  screenshots were of the editor before the overhaul and are replaced by text.
  Correct it as you use it.
---

When the assistant answers, it changes the rules in the **Rules** list on the left. Each row is one box, with its picture, its name and what it takes. Two things are worth checking every time.

**Order matters.** A piece goes to the first rule that takes it. A part that could go in two boxes goes in the higher one. If everything is landing in one box, that box is probably too high in the list and too broad.

**The last row is doing the work you cannot see.** Anything that no rule takes is dealt with by the **Everything else** row at the bottom: all together in one box, or sorted into a bin for each category or color. If that box is enormous, your rules are narrower than you think.

## How a piece falls through the list

The machine tells the profile two things about a piece: which part it is, and which color. Then:

1. It tries the rules from the top. A rule either takes the piece, and the piece goes to its box, or does not, and the piece moves on to the next rule. A rule that is turned off (**Turn off**, above the chosen rule or in the menu on its row) is skipped.
2. If no rule takes it, the **fallback** does. You choose on the **Everything else** row what that is: one bin for each BrickLink category, each Rebrickable category, or each color.
3. With **All together**, every piece left over goes into Everything else. That box is not a bin on the machine: it is the [discard bin]({{ '/hive/first-profile/send-it-to-your-machine/#pieces-that-go-to-the-discard-bin' | relative_url }}) under it.

A rule only takes what it describes, so a **color** box takes only the colors it names and everything else carries on. A rule with no conditions takes nothing.

Click a rule to see which parts it matches. The **Matches** tab lists them, and that list is what the rule actually does. The **Categories** tab shows every bin, and a **Where would a piece go?** box: give it a part and a color, and it says which box the draft sends that piece to and why (a rule, a kit, the fallback, or nothing, which means Everything else). It answers again as you change the draft.

The editor marks a rule that cannot do its job, and says why on the rule:

- *Rules above this one already take every part it matches.* Move it up, or take it out.
- *No part in the catalog matches this rule.*
- *This rule has no conditions yet, so it takes nothing.*
- *Nothing reaches this rule: X takes every piece first.*
- *N of this kit's parts go to rules above it; move the kit up to collect them.*

A condition Hive cannot read stops the save. The message says how many problems there are, and each one is shown on its rule and its condition.

## Conditions, all of, any of, and groups

Pick a rule and you see its conditions. A condition is three choices, never typed as data: a **field** (named for what it is, grouped as Part, Color, Category, Year, Size and Price), how it is **compared**, and its **value**. Parts are searched and shown by picture, colors are chosen by swatch, categories by name, and numbers carry their unit. **Add condition** adds another line to the rule.

The comparisons, as the editor words them:

- **is** and **is not** are exactly this value, and anything except it.
- **is one of** and **is not one of** take a list of values.
- **contains** looks for text inside a name, and **matches** is a pattern (a regular expression) for the same job. Both ignore case.
- **is at least** and **is at most** compare numbers, for fields like a year, a weight or a price.

Which comparisons you get depends on the field you picked. A name can be searched with **contains**, and not compared with **is at least**.

**The choice at the top of the rule decides how its conditions combine.** **All of** means every condition has to be true, which is "and". **Any of** means one is enough, which is "or". A rule on **all of** with two conditions catches only parts that satisfy both.

**Add group** adds a group inside the rule. A group is not a separate box. It is worked out on its own, with its own **all of** or **any of**, and its answer then counts as one more true or false alongside the rule's own conditions. That is how you mix and with or. A new group starts on the opposite of the rule around it, since mixing the two is what a group is for. Groups can hold groups, two levels deep.

For example, a box for red tiles and blue plates is a rule on **any of** with two groups, and each group is **all of** two conditions:

- Group 1, **all of**: BrickLink category is Tile, and Color is Red.
- Group 2, **all of**: BrickLink category is Plate, and Color is Blue.

And "tiles that are red or blue" is the other way around: a rule on **all of** with BrickLink category is Tile, and a group on **any of** with Color is Red and Color is Blue.

**There is no "not" for a group.** To leave something out, use **is not** or **is not one of** on a condition: "dark bluish grey, but not plates" is a rule on **all of** with two conditions: Color is Dark Bluish Gray, and BrickLink category is not one of Plate, Plate Modified. Or put the box that wants those parts above, and let the rest carry on down the list.

## An example: four boxes in the right order

A profile with four boxes, in the order the machine tries them:

<ol class="numbered-steps">
  <li><strong>Minifigure over 5</strong>, on <strong>all of</strong>: Lowest price, used is at least 5 ($), and Rebrickable category name contains <code>minifig</code>. Minifigure parts worth five dollars or more.</li>
  <li><strong>Minifigure</strong>, on <strong>any of</strong>: Rebrickable category name contains <code>minifig heads</code>, or <code>minifig upper</code>, or <code>minifigs</code>, or <code>minifig lower</code>, or <code>minifig headwear</code>. Every other minifigure part.</li>
  <li><strong>Black</strong>: Color is Black. Anything black.</li>
  <li><strong>Red, Dark Red</strong>: Color is one of Red, Dark Red. Anything in either red.</li>
</ol>

**Put the minifigure boxes above the colour boxes.** Black hair and black legs are minifigure parts and they are also black, so whichever rule is higher takes them. In this order they go in with the rest of the minifigure parts. Put **Black** on top instead and the black box takes them, and your minifigure box comes out with no black in it.

**Put Minifigure over 5 above plain Minifigure** if you want the valuable parts separated. A five dollar hairpiece is an ordinary minifigure part as well, and the plain box takes it the moment it is the higher of the two.

**A colour box only takes the colours it names.** Everything it does not claim carries on down the list, so a black box near the bottom does not empty the boxes under it. It takes their black and leaves the rest.

**Put a kit above broader rules.** A kit takes its parts only while it still needs them, and then lets them go on. If a broader rule is above it, that rule takes the kit's parts first and the kit never fills. [Kits and their counts]({{ '/hive/first-profile/send-it-to-your-machine/#kits-and-their-counts' | relative_url }}) has the rest.

**To change the order**, drag a rule by its row in the list. From a keyboard, hold Alt and press the up or down arrow on a row. **Move up** and **Move down** are above the chosen rule and in the menu on its row.

**Type numbers on their own.** The value in the **Minifigure over 5** rule is `5`, and the editor shows the unit ($ for prices, g for weight, studs for size) after the box. A value that is not a number is a problem that stops the save, and it is shown on its condition.

Next: [send it to your machine]({{ '/hive/first-profile/send-it-to-your-machine/' | relative_url }}).

Back to [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}).

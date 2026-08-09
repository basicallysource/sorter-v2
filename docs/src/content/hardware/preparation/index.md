---
layout: default
title: Preparation
type: how-to
section: hardware
slug: preparation
kicker: Hardware — Preparation
lede: Prep done to parts before assembly. Right now that means pressing heat inserts.
permalink: /hardware/preparation/
---

## Heat inserts

Press the inserts into these parts before assembly — see [installing heat inserts]({{ '/hardware/helpers/heat-inserts/' | relative_url }}).

<table>
  <thead>
    <tr><th>Part</th><th>Insert</th><th>Qty</th></tr>
  </thead>
  <tbody>
    {% for pair in site.data.parts %}
      {% assign part = pair[1] %}
      {% if part.heat_inserts %}
        {% for hi in part.heat_inserts %}
          {% assign insert = site.data.parts[hi.insert] %}
          <tr>
            <td>{{ part.name }}</td>
            <td>{% if insert %}{{ insert.name }}{% else %}{{ hi.insert }}{% endif %}</td>
            <td>{{ hi.qty }}</td>
          </tr>
        {% endfor %}
      {% endif %}
    {% endfor %}
  </tbody>
</table>

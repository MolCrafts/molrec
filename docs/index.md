---
title: MolRec
description: Backend-neutral record contract for the MolCrafts ecosystem.
hide:
  - navigation
  - toc
hero:
  kicker: MolRec Specification
  title: MolRec
  description: "One standard for heterogeneous molecular records — high information density, FAIR by construction. Systems, snapshots, trajectories, observables, and run logs in a single self-describing package."
  install:
    label: Install
    command: pip install molrec
  badges:
    - img: https://img.shields.io/badge/python-3.12%2B-blue.svg
      href: https://github.com/MolCrafts/molrec
      alt: Python 3.12+
    - img: https://img.shields.io/badge/license-BSD--3-Clause-18432B?style=flat-square
      href: https://github.com/MolCrafts/molrec/blob/master/LICENSE
      alt: License BSD-3-Clause
  actions:
    - label: Specification
      href: spec/specification/
      style: primary
    - label: Conventions
      href: spec/conventions/
    - label: Why Zarr
      href: spec/zarr/
---

<h1 class="molcrafts-sr-only">MolRec</h1>

<div class="molcrafts-manual-home" markdown>

<section class="molcrafts-manual-section molcrafts-manual-section--compact" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">At a glance</span>

## One standard, one root

A record is the unit of interchange. Heterogeneous payload — definition,
state, time series, observables, and run logs — under a single
self-describing root. A reader walks it from the groups on disk.

</div>

```text
root
 \-- meta
 \-- (system)
 \-- (frame)
 \-- (trajectory)
 \-- (forcefield)
 \-- (observables)
 \-- (method)
 \-- (status)
 \-- (metrics)
```

</section>

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">Features</span>

## One standard for heterogeneous, FAIR records

</div>

<div class="molcrafts-manual-grid molcrafts-manual-grid--cols-2">
  <a href="spec/specification/">
    <strong>One standard</strong>
    <em>One contract. Every MolCrafts tool opens the same root.</em>
  </a>
  <a href="spec/overview/">
    <strong>Heterogeneous</strong>
    <em>Topology, state, observables, and runs in one package.</em>
  </a>
  <a href="spec/ragged/">
    <strong>High density</strong>
    <em>Write on change. No padded <code>N_max</code>. File count ignores <code>nstep</code>.</em>
  </a>
  <a href="spec/zarr/">
    <strong>FAIR</strong>
    <em>Self-describing, open, reusable.</em>
  </a>
</div>

</section>

<section class="molcrafts-manual-section molcrafts-manual-section--stack" markdown>

<div class="molcrafts-manual-section__header" markdown>

<span class="molcrafts-manual-eyebrow">Find your page</span>

## Specification, then the binding

</div>

<nav class="molcrafts-manual-index" aria-label="Documentation entry points">
  <a href="layout/">
    <span>00</span>
    <strong>Layout by example</strong>
    <em>Annotated trees of real records, generated from the codecs: what lands on disk.</em>
  </a>
  <a href="spec/specification/">
    <span>01</span>
    <strong>Objective</strong>
    <em>Scope, notation, and how a record is organised.</em>
  </a>
  <a href="spec/overview/">
    <span>02</span>
    <strong>Overview</strong>
    <em>Sections, how they compose, and how to add your own content.</em>
  </a>
  <a href="spec/conventions/">
    <span>03</span>
    <strong>Conventions</strong>
    <em>Standardized identifiers: <code>atoms</code>, <code>atomi</code>/<code>atomj</code>, split coordinates.</em>
  </a>
  <a href="spec/zarr/">
    <span>04</span>
    <strong>Why Zarr V3</strong>
    <em>What Zarr V3 gives a record, and how a scientific path is branded <code>*.mrec/</code>.</em>
  </a>
  <a href="spec/storage/">
    <span>05</span>
    <strong>Root layout</strong>
    <em>Groups, documents as attributes, host metrics vs a scientific package.</em>
  </a>
  <a href="spec/ragged/">
    <span>06</span>
    <strong>Ragged trajectory</strong>
    <em>CSR layout, present / empty / absent blocks, pinned <code>sequence_schema</code>, growth example.</em>
  </a>
</nav>

</section>

</div>

# Historical source publication review — 2026-10-09

The original [2026-PG-robotalk source](https://github.com/BlackChila/2026-PG-robotalk)
recorded a publication review at `045fe22` plus pending documentation changes.
That review predates this conversation-focused repository. It did not run the
application, camera, robot or a clean Linux installation, and its statements
about old GitHub visibility, topics, issues and release state do not describe
SO101-robotalk.

## Ownership and project license

The source review records the maintainer's confirmation of sole authorship, no
copied project code and no employer/university obligations. Original code and
documentation use [Apache-2.0](../LICENSE), with attribution in [NOTICE](../NOTICE).
Upstream code, services, weights and voices retain their separate terms; see
[the third-party inventory](third-party-materials.md). This continuation keeps
the license and source attribution.

The source review records Apache-2.0/GPLv3 compatibility for the original Piper
worker. It does not relicense Piper or remove applicable requirements when
distributing a combined worker/Piper program. Check the upstream licenses and
notices for the exact distribution.

## Credential and privacy checks

The historical review used a standard-library pattern scan over 24 locally
reachable commits, 542 Git blob/commit/tag objects and 221 tracked/nonignored
files. It identified no real credential; the 73 credential-shaped matches were
reviewed as synthetic test keys or dummy URL data. No dedicated secret scanner
was installed. These figures describe that historical scan only; they do not
certify later commits, binary content, the new repository or every secret format.

Original-host paths, email identities, hardware IDs, calibration fingerprints
and private-network addresses occur in the inherited source/history. They are
setup identifiers rather than authentication credentials. Removing current
references does not erase old Git objects in the source repository. This
repository starts from a cleaned snapshot and does not import the old Git history.

The [empty environment example](../.env.example) uses `OPENAI_API_KEY`; populated
`.env` files are ignored. `SO101_LM_STUDIO_TOKEN` is exported separately. Generated
logs, audio, camera snapshots and outputs may contain private data and must be
reviewed before sharing.

## Bundled media and recordings

The active intro bundle contains versioned audio and robot joint trajectories,
selected by `assets/demo/intro/active.json`. It is tied to the original calibration.
The source review did not establish redistribution permission for all bundled
media; its exclusion from the project license is retained. The old UI design
explorations are omitted from this repository's current tree.

A publication of source does not commission a robot or establish installation,
motion safety, task reliability or bundled-media rights. Remaining release work
is tracked in [the publication checklist](publishing-checklist.md).

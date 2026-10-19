# Contributing

A useful report includes the command or UI settings, physical units, intended size, Python/OS version and `report.json`. Include a small model only when you own it or may redistribute it; do not upload confidential client parts.

Use deterministic geometry fixtures to demonstrate topology or repair changes. Check the original, repaired geometry and the bytes actually exported to STL/3MF. Preserve disconnected components and cavity orientation. A closed edge graph alone does not prove a solid is valid or printable.

New repairs must require explicit consent, state their eligibility limits and report skipped cases. Include examples where the repair should refuse to change geometry. Keep uncertain volume/thickness results unavailable rather than implying certification.

Run the README test commands before proposing a change. Slicer validation should name the application/version, imported format and units, and include actual observed results. Physical print validation should also record printer/material/settings; a rendered preview is not a print test.

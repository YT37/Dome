# Hand-check shortlist

Best 10 of 25 deep-checked unit scans (from 60 CoStar apartment/condo properties, mid-rise first). Ranked: multifamily, then floor plan + cube faces + oblique + footprint all present, then most inside windows (simple detector, 6 sweeps max).

Location used = Matterport geocoordinates, else the CoStar record.

| # | scan_id | name | CoStar property | CoStar type | floors | units | floor plan | cube faces | sweeps | inside windows | obliques | footprint | geocoords |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `6WjHU7zCbLh` | 2 BR, 2 BA - 1,573 SF | CS-10183484 | multifamily | 7 | 226 | yes | yes | 19 | 32 | NESW | yes | yes |
| 2 | `2wR7pG5V7cE` | Calais Midtown - The Crawford - 1 Bedroom, 1 Bathroom – Features will vary in each apartment | CS-7768847 | multifamily | 6 | 352 | yes | yes | 19 | 28 | NESW | yes | yes |
| 3 | `4niEDRQCmJp` | Belmont Station - Plan San Bernadino - 1 Bed / 1.5 Bath plus Loft | CS-6964921 | multifamily | 4 | 178 | yes | yes | 23 | 23 | NESW | yes | yes |
| 4 | `BquSkXfGC5y` | 2BR, 2BA - 1374SF | CS-9744061 | multifamily | 5 | 219 | yes | yes | 38 | 22 | NESW | yes | no |
| 5 | `MnkmDZdURsH` | 2 BR, 2 BA -Capri Premier | CS-1585983 | multifamily | 4 | 562 | yes | yes | 18 | 22 | NESW | yes | no |
| 6 | `AtGvPtdwQNY` | 2BR, 2BA - 1065SF | CS-6259474 | multifamily | 4 | 281 | yes | yes | 26 | 18 | NESW | yes | yes |
| 7 | `3DktHSAea7f` | Oakridge, 2 Bed / 2 Bath - Caldwell | CS-9874409 | multifamily | 4 | 350 | yes | yes | 28 | 10 | NESW | yes | yes |
| 8 | `6xDzQSw8iwE` | 3BR, 3BA - 2,196SF | CS-18911082 | multifamily | 4 | 365 | yes | yes | 50 | 9 | NESW | yes | yes |
| 9 | `4i63DGcPxvY` | 1BR, 1BA - B4 - 1,247SF | CS-15439231 | multifamily | 5 | 231 | yes | yes | 23 | 5 | S | yes | yes |
| 10 | `7hEGKRbLZzU` | SageLA - Plan 35 Studio - 3D Tour May Include Virtual Staging and is for Illustrative Purposes Only | CS-11044249 | multifamily | 6 | 267 | yes | yes | 10 | 0 | NESW | yes | no |

Next: `python -m dome.tools.handcheck <scan_id>` on the top pick.

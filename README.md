# TrailKeeper maps

Offline topographic map files for the TrailKeeper hiking app, one file per region.
This repository holds only open map data and the scripts that convert it. There are
no keys, accounts or personal data here.

The app downloads a region from this repository's `maps` release only when you tap
**Download** in the Maps tab, and you can delete it again at any time.

## Regions

| Country | Regions | Source | Licence |
|---|---|---|---|
| Netherlands | 12 provinces | Kadaster TOP25raster (1:25,000), via PDOK | CC BY 4.0 |
| Austria | 9 states | BEV KM50-R (1:50,000) with relief | CC BY 4.0 |

Each region is cut along the province or state border plus about 3 km, so a walk
that crosses the border a little stays on the map. Borders come from Natural Earth
(public domain).

Zoom levels 8 to 15 are stored; the app enlarges level 15 when you zoom in further.

## Attribution

- Netherlands: © Kadaster / PDOK, TOP25raster, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Austria: © BEV (Bundesamt für Eich- und Vermessungswesen), KM50-R, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Borders: Natural Earth (public domain)

The converted files are reprojected to Web Mercator, resampled and cut to region
borders. They are published under the same CC BY 4.0 licence.

## How the files are made

`.github/workflows/build-maps.yml` runs by hand (Actions → Build maps → Run workflow).
For each region it downloads the source map sheets, reprojects them with GDAL,
writes WebP tiles to MBTiles and converts that to a single `.pmtiles` file with
[go-pmtiles](https://github.com/protomaps/go-pmtiles). A last step writes
`catalog.json` (names, sizes, MD5 checksums) that the app reads.

Scripts are released under the MIT licence.

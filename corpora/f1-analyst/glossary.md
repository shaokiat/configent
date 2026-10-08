Terms a user says, and what they mean in this schema. A driver is named by `drivers.forename`
and `drivers.surname` (there is no single name column); a team is a `constructors` row.

- **pole, pole position**: `results.grid = 1`. `qualifying.position = 1` is the fastest
  qualifier, which can differ when a grid penalty applies. Prefer `results.grid`.
- **grid slot 0** (`results.grid = 0`): started from the pit lane. Not a pole.
- **win, won the race**: `results.positionOrder = 1`. Use `positionOrder`, not `position`
  (`position` is NULL for a driver who did not finish).
- **podium**: `results.positionOrder` between 1 and 3.
- **finished the race**: `results.position IS NOT NULL` (`positionText = 'R'` is retired,
  other letters are disqualified / excluded / not classified). A lapped finisher still has a position.
- **DNF**: `results.position IS NULL`; the reason is `status.status` through `results.statusId`.
- **fastest lap** of a race: `results.rank = 1`. `rank` is only filled from 2004 on.
  `results.fastestLapTime` is text like `1:27.452`; compare as text only within one race.
- **lap time**: `lapTimes.milliseconds` (numeric). Prefer it to the text `lapTimes.time`.
- **pit stop duration**: `pitStops.milliseconds`; `pitStops.duration` is text in seconds.
- **championship, title, champion**: the driver (or constructor) with `position = 1` in
  `driverStandings` (`constructorStandings`) at the **last round of the season**. Standings
  rows are cumulative per race, so never sum them. A "title" count is the number of seasons
  where that is true.
- **wins in a season**: `driverStandings.wins` at the last round, or count `positionOrder = 1`.
- **points in a season**: `driverStandings.points` at the last round, or `SUM(results.points)`
  over the season's races. `constructorResults.points` is a team's points in one race.
- **season, year**: `races.year` (equal to `seasons.year`). **round**: the race's order in the season.
- **Grand Prix**: a `races` row; the name is `races.name`, the venue is `circuits` through `races.circuitId`.
- **nationality**: demonyms such as `British`, `German`, not country names. Circuits use `country`
  names such as `UK` or `Germany`. Do not mix the two.
- **driver code**: three letters, e.g. `HAM`; NULL for many older drivers.
- **team, constructor, manufacturer**: `constructors.name`.
- **qualifying stages**: `q1`, `q2`, `q3` (text lap times). A driver knocked out earlier has
  NULL in the later stages. Qualifying rows exist from 1994.

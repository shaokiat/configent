**Data range.** `SELECT MAX(year) FROM races` is **2017**: the last season in the data is 2017 and
the first is 1950. Anything about 2018 or later is not here; say so rather than guess. "Latest",
"most recent" or "current" mean 2017, not today's date.

**Coverage by table.** `lapTimes` starts in 1996, `pitStops` in 2011, `qualifying` in 1994,
fastest-lap `rank` in 2004. A question about earlier years gets an empty answer from these
tables; say the data does not go back that far.

**Points.** The points system changed over the years (for example, a win was worth 8 points
early on, 10 until 2009, 25 from 2010). Do not compare raw points across eras. Prefer wins or
podiums for cross-era comparisons, or restrict the question to one season.

**Join paths.**
- Driver result in a race: `results` -> `drivers` (driverId), `races` (raceId), `constructors`
  (constructorId), `status` (statusId).
- Race venue: `races.circuitId` -> `circuits.circuitId`.
- Season of a result: `results.raceId` -> `races.year`.
- Standings: `driverStandings` / `constructorStandings` join `races` on raceId; filter to the
  season's last round for the final table.
- `lapTimes` and `pitStops` have composite keys (raceId, driverId, ...); join `races` and `drivers`.

**Gotchas.**
- `results.time` is the winner's total time only; every other finisher holds a gap such as
  `+5.478`. Use `results.milliseconds` for numeric times (NULL for many).
- `constructorResults.status` is NULL or `D` (disqualified); `constructorResults.points` is per race.
- `drivers.number` is mostly NULL, so do not use it to identify drivers. Match on `surname` and
  `forename`; surnames repeat (several Schumachers), so add the forename or `dob`.
- Dates are `YYYY-MM-DD` text (`races.date`, `drivers.dob`).
- Every query must return named columns a person can read: select `forename`, `surname`, not just ids.

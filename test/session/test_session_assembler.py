"""Test cases for the session assembler, which takes a stream of packets and produces
one ``SessionResult`` per session UID. The assembler is responsible for joining the player's
lap traces, the player's setup, and the final classification into a single deliverable.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from f1telemetry.src.protocol.enums import (
    DriverStatus,
    Formula,
    PacketId,
    PitStatus,
    ResultStatus,
    SafetyCarStatus,
    SessionType,
    Weather
)
from f1telemetry.src.session.assembler import _MAX_LAP_START_DISTANCE_M, assemble


def _hdr(pid, uid, frame=0, player=0):
    """Build a fake packet header for testing."""
    return SimpleNamespace(packet_id=pid, session_uid=uid, frame_identifier=frame,
                           packet_format=2025, player_car_index=player)


def _car_lap(lap_num, distance, driver_status=DriverStatus.ON_TRACK,
             pit_status=PitStatus.NONE, pit_lane_timer_active=0):
    """A minimal Lap Data entry for the player's car. Carries the classification-fallback fields
    (position/grid/stops/penalties/status) that reconstruct_classification reads when a stream has
    no Final Classification packet - as these assembler streams don't.

    The lap-state fields default to a plain racing lap, so every stream that isn't about them reads
    as one; ``frames`` passes them through for the ones that are.
    """
    return SimpleNamespace(current_lap_num=lap_num, lap_distance=distance,
                           car_position=1, grid_position=1, num_pit_stops=0,
                           penalties=0, result_status=int(ResultStatus.FINISHED),
                           driver_status=int(driver_status), pit_status=int(pit_status),
                           pit_lane_timer_active=pit_lane_timer_active)


def session_pkt(uid, stype=SessionType.RACE, laps=5, safety_car=SafetyCarStatus.NONE,
                red_flag_periods=0):
    """Build a fake session packet for testing."""
    return SimpleNamespace(
        header=_hdr(PacketId.SESSION, uid),
        season_link_identifier=uid, weekend_link_identifier=uid, session_link_identifier=uid,
        track_id=7, session_type=int(stype), formula=int(Formula.F1_MODERN),
        weather=int(Weather.CLEAR), game_mode=28, total_laps=laps, ai_difficulty=95,
        num_sessions_in_weekend=0, weekend_structure=[0] * 12,
        safety_car_status=int(safety_car), num_red_flag_periods=red_flag_periods,
        track_length=5000.0, sector_2_lap_distance_start=1500.0, sector_3_lap_distance_start=3000.0,)


def participants_pkt(uid):
    """Build a fake participants packet for testing."""
    return SimpleNamespace(
        header=_hdr(PacketId.PARTICIPANTS, uid), num_active_cars=2,
        participants=[
            SimpleNamespace(name=b"You", team_id=2, driver_id=9, race_number=16,
                            nationality=8, ai_controlled=0, network_id=1),
            SimpleNamespace(name=b"Rival", team_id=0, driver_id=3, race_number=1,
                            nationality=10, ai_controlled=1, network_id=0)])


def _lap_entry(t, vb, sectors=None):
    """Build a fake Session History lap entry for testing."""
    if sectors is None and t:
        third = t // 3
        sectors = [(0, third), (0, third), (0, t - 2 * third)]
    elif sectors is None:
        sectors = [(0, 0), (0, 0), (0, 0)]
    (m1, s1), (m2, s2), (m3, s3) = sectors
    return SimpleNamespace(
        lap_time_in_ms=t,
        sector1_time_ms_part=s1, sector1_time_minutes_part=m1,
        sector2_time_ms_part=s2, sector2_time_minutes_part=m2,
        sector3_time_ms_part=s3, sector3_time_minutes_part=m3,
        lap_valid_bit_flags=vb)


def sh_pkt(uid, entries, player=0, best_lap_num=0, car_idx=None):
    """Build a fake Session History packet for testing."""
    return SimpleNamespace(header=_hdr(PacketId.SESSION_HISTORY, uid, player=player),
                           car_idx=player if car_idx is None else car_idx,
                           num_laps=len(entries), best_lap_time_lap_num=best_lap_num,
                           lap_history_data=entries,
                           num_tyre_stints=0, tyre_stints_history_data=[])


_frame = [0]
def frames(uid, lap_num, distances, player=0, driver_status=DriverStatus.ON_TRACK,
           pit_status=PitStatus.NONE, pit_lane_timer_active=0, speed=200):
    """Build a sequence of fake Lap Data + Car Telemetry packets for testing.
    Each distance in `distances` is a separate frame, and the frame identifier is incremented for each frame.
    The lap number is constant for all frames, and the session UID is constant.

    The lap-state arguments apply to every frame of the call, so a lap made of several ``frames``
    calls can change state part-way through - which is how a real in-lap or out-lap reads.
    ``speed`` matters whenever a lap number carries more than one pass: the assembler picks the
    timed run by integrating distance/speed, so a pit-lane run has to be *slow* or it competes with
    the flying lap on distance alone."""
    out = []
    for d in distances:
        _frame[0] += 1
        f = _frame[0]
        out.append(SimpleNamespace(header=_hdr(PacketId.LAP_DATA, uid, frame=f, player=player),
                                   lap_data=[_car_lap(lap_num, d, driver_status, pit_status,
                                                      pit_lane_timer_active)]))
        out.append(SimpleNamespace(header=_hdr(PacketId.CAR_TELEMETRY, uid, frame=f, player=player),
                                   car_telemetry_data=[SimpleNamespace(
                                       speed=200, throttle=1.0, brake=0.0, steer=0.0,
                                       gear=7, engine_rpm=10000, drs=0,
                                       tyres_surface_temperature=(90, 90, 90, 90),
                                       tyres_inner_temperature=(95, 95, 95, 95),
                                       brakes_temperature=(300, 300, 300, 300),
                                       engine_temperature=110)]))
    return out


def status_pkt(uid, compound=16, visual=16, age=1, player=0, fuel=50.0):
    """Fake Car Status packet: the player's tyre compound + age, fuel (and zeroed ERS)."""
    return SimpleNamespace(
        header=_hdr(PacketId.CAR_STATUS, uid, player=player),
        car_status_data=[SimpleNamespace(
            actual_tyre_compound=compound, visual_tyre_compound=visual,
            tyres_age_laps=age, ers_store_energy=0.0, ers_deploy_mode=0, fuel_in_tank=fuel)])


def motion_pkt(uid, pos_x, pos_z, g_lat, g_long, frame, player=0):
    """Fake Motion packet for the player's car (2025 header: g-force already float g)."""
    return SimpleNamespace(
        header=_hdr(PacketId.MOTION, uid, frame=frame, player=player),
        car_motion_data=[SimpleNamespace(
            world_position_x=pos_x, world_position_y=0.0, world_position_z=pos_z,
            g_force_lateral=g_lat, g_force_longitudinal=g_long)])


def motion_frames(uid, lap_num, points, player=0):
    """Like `frames`, but each point is (distance, pos_x, pos_z, g_lat, g_long) and a Motion
    packet precedes the frame's Lap Data + Car Telemetry (same frame id)."""
    out = []
    for d, x, z, gl, gL in points:
        _frame[0] += 1
        f = _frame[0]
        out.append(motion_pkt(uid, x, z, gl, gL, frame=f, player=player))
        out.append(SimpleNamespace(header=_hdr(PacketId.LAP_DATA, uid, frame=f, player=player),
                                   lap_data=[_car_lap(lap_num, d)]))
        out.append(SimpleNamespace(header=_hdr(PacketId.CAR_TELEMETRY, uid, frame=f, player=player),
                                   car_telemetry_data=[SimpleNamespace(
                                       speed=200, throttle=1.0, brake=0.0, steer=0.0,
                                       gear=7, engine_rpm=10000, drs=0,
                                       tyres_surface_temperature=(90, 90, 90, 90),
                                       tyres_inner_temperature=(95, 95, 95, 95),
                                       brakes_temperature=(300, 300, 300, 300),
                                       engine_temperature=110)]))
    return out


def damage_pkt(uid, wear=(0.0, 0.0, 0.0, 0.0), tyre_damage=(0, 0, 0, 0), blisters=(0, 0, 0, 0),
               brakes=(0, 0, 0, 0), player=0, **overrides):
    """Fake Car Damage packet: per-wheel tyre wear/damage/blisters + car-body damage."""
    fields = dict(
        tyres_wear=list(wear), tyres_damage=list(tyre_damage), tyre_blisters=list(blisters),
        brakes_damage=list(brakes),
        front_left_wing_damage=0, front_right_wing_damage=0, rear_wing_damage=0,
        floor_damage=0, diffuser_damage=0, sidepod_damage=0,
        drs_fault=0, ers_fault=0, gearbox_damage=0, engine_damage=0,
        engine_mguh_wear=0, engine_es_wear=0, engine_ce_wear=0, engine_ice_wear=0,
        engine_mguk_wear=0, engine_tc_wear=0, engine_blown=0, engine_seized=0)
    fields.update(overrides)
    return SimpleNamespace(header=_hdr(PacketId.CAR_DAMAGE, uid, player=player),
                           car_damage_data=[SimpleNamespace(**fields)])



def _setup_entry(**overrides):
    """A full CarSetupData entry with sane defaults; override any field (e.g. front_wing)."""
    fields = dict(
        front_wing=5, rear_wing=5, on_throttle=50, off_throttle=50,
        front_camber=-3.0, rear_camber=-1.5, front_toe=0.1, rear_toe=0.2,
        front_suspension=1, rear_suspension=1, front_anti_roll_bar=1, rear_anti_roll_bar=1,
        front_suspension_height=3, rear_suspension_height=4,
        brake_pressure=95, brake_bias=58, engine_braking=50,
        rear_left_tyre_pressure=22.0, rear_right_tyre_pressure=22.0,
        front_left_tyre_pressure=23.0, front_right_tyre_pressure=23.0,
        ballast=0, fuel_load=10.0)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def setup_pkt(uid, player=0, **overrides):
    """Fake Car Setups packet for the player's car."""
    return SimpleNamespace(
        header=_hdr(PacketId.CAR_SETUPS, uid, player=player),
        car_setups=[_setup_entry(**overrides)])


class SessionSplitTest(unittest.TestCase):
    """Test cases for splitting a stream of packets into one result per session UID."""
    def test_splits_stream_into_one_result_per_session(self):
        """Two sessions in the stream produce two results, each with its own UID."""
        stream = []
        for uid in (100, 200):
            stream += [session_pkt(uid), participants_pkt(uid)]
            stream += frames(uid, 1, [0, 1500, 3000])
            stream += frames(uid, 2, [0, 1500])           # lap 2 trailing
            stream.append(sh_pkt(uid, [_lap_entry(80000, 0x0F), _lap_entry(0, 0x00)]))
        results = list(assemble(stream))
        self.assertEqual(len(results), 2)
        self.assertEqual([r.session_uid for r in results], [100, 200])

    def test_uid_zero_init_packets_ignored(self):
        """Packets with session UID 0 are ignored, and the first non-zero UID is used."""
        stream = [session_pkt(0)]                         # frame-1 init: uid 0
        stream += [session_pkt(100), participants_pkt(100)]
        stream += frames(100, 1, [0, 1500, 3000]) + frames(100, 2, [0])
        stream.append(sh_pkt(100, [_lap_entry(80000, 0x0F), _lap_entry(0, 0x00)]))
        results = list(assemble(stream))
        self.assertEqual([r.session_uid for r in results], [100])


class FinalLapRecoveryTest(unittest.TestCase):
    """The headline fix: the last lap has no following transition, but Session History
    carries its time, so the trailing buffer's trace joins and the lap is emitted."""

    def test_trailing_lap_is_emitted_from_session_history(self):
        """The final lap has no following transition, but Session History carries its time,
        so the trailing buffer's trace joins and the lap is emitted."""
        stream = [session_pkt(1), participants_pkt(1)]
        stream += frames(1, 1, [0, 1500, 3000])
        stream += frames(1, 2, [0, 1500, 3000])
        stream += frames(1, 3, [0, 1500, 3000, 4000])     # final lap, no transition after
        stream.append(sh_pkt(1, [_lap_entry(72000, 0x0F),
                                 _lap_entry(70000, 0x0F),
                                 _lap_entry(69000, 0x0F)]))
        (race,) = list(assemble(stream))
        self.assertEqual([l.lap_number for l in race.laps], [1, 2, 3])
        self.assertEqual([l.lap_time_ms for l in race.laps], [72000, 70000, 69000])
        self.assertIsNotNone(race.laps[-1].trace)
        self.assertEqual(len(race.laps[-1].trace), 4)     # trailing buffer captured


class InLapDroppedTest(unittest.TestCase):
    """An in-lap with no following lap is dropped if its Session History time is zero,
    because the player did not complete the lap and the trace is not joined."""
    def test_inlap_with_zero_session_history_time_is_dropped(self):
        """The in-lap has no following lap, and its Session History time is zero, so it is dropped."""
        stream = [session_pkt(1, SessionType.QUALIFYING_1, laps=1), participants_pkt(1)]
        stream += frames(1, 1, [0, 1500, 3000])           # flying lap
        stream += frames(1, 2, [0, 1500])                 # in-lap, trailing
        stream.append(sh_pkt(1, [_lap_entry(85000, 0x0F),
                                 _lap_entry(0, 0x00)]))    # lap 2 not completed -> time 0
        (quali,) = list(assemble(stream))
        self.assertEqual([l.lap_number for l in quali.laps], [1])
        self.assertEqual(quali.laps[0].lap_time_ms, 85000)


class DistanceGuardTest(unittest.TestCase):
    """The guard that keeps a mid-lap join out of the results, and what it must not catch."""

    def test_lap_starting_far_from_line_is_not_emitted(self):
        """A lap joined well past the line is dropped, even though Session History has a time for it.

        Derived from the constant rather than pinned to a number: a fixture sitting on the exact
        threshold is how a later widening of the bound went unnoticed.
        """
        stream = [session_pkt(1), participants_pkt(1)]
        stream += frames(1, 1, [_MAX_LAP_START_DISTANCE_M + 100, 1500, 3000])
        stream += frames(1, 2, [5, 1500, 3000])           # trailing, starts near line
        stream.append(sh_pkt(1, [_lap_entry(90000, 0x0F),
                                 _lap_entry(85000, 0x0F)]))
        (race,) = list(assemble(stream))
        self.assertEqual([l.lap_number for l in race.laps], [2])

    def test_a_standing_start_from_a_distant_grid_slot_is_kept(self):
        """A race's lap 1 begins at its grid slot, which can sit a long way past the timing line.

        The bound is set by pole, not by the back of the grid: the grid queues *backwards* from P1
        towards the line, so a slot further down sits nearer to it — and on a circuit where pole is
        already close, the lower slots fall behind the line entirely and their lap 1 starts from a
        few metres, well inside the guard. So the deepest case on the calendar is P1 at COTA, about
        323 m. Measured here: Jeddah 246.5 m, Shanghai 175.7 m.

        These are real opening laps, not mid-lap joins, and a bound that clips them loses the race
        start silently — the session simply has no lap 1.
        """
        for start_m in (175.7, 246.5, 323.0):
            with self.subTest(grid_slot_m=start_m):
                stream = [session_pkt(1), participants_pkt(1)]
                stream += frames(1, 1, [start_m, 1500, 3000])
                stream += frames(1, 2, [5, 1500, 3000])
                stream.append(sh_pkt(1, [_lap_entry(90000, 0x0F),
                                         _lap_entry(85000, 0x0F)]))
                (race,) = list(assemble(stream))
                self.assertEqual([l.lap_number for l in race.laps], [1, 2])

    def test_the_bound_clears_the_deepest_known_grid_slot(self):
        """COTA's pole slot is the furthest past the line on the calendar, about 323 m.

        Pinned because the reason for the number is circuit geometry, not anything visible in the
        code — so a later tightening that looks harmless would go back to dropping race starts with
        nothing to say so.
        """
        self.assertGreater(_MAX_LAP_START_DISTANCE_M, 323)


class TimingDetailTest(unittest.TestCase):
    """Test cases for recombining the sector times from minutes + milliseconds parts."""
    def _one_lap_session(self, entry):
        """Build a one-lap session with the given Session History lap entry."""
        stream = [session_pkt(1), participants_pkt(1)]
        stream += frames(1, 1, [0, 1500, 3000])
        stream += frames(1, 2, [0, 1500])                 # trailing, dropped (time 0)
        stream.append(sh_pkt(1, [entry, _lap_entry(0, 0x00)]))
        (race,) = list(assemble(stream))
        return race.laps[0]

    def test_validity_from_bit_flags(self):
        """The lap's validity is determined by the Session History lap_valid_bit_flags field."""
        valid = self._one_lap_session(_lap_entry(80000, 0x0F))    # 0x08 set
        invalid = self._one_lap_session(_lap_entry(80000, 0x07))  # 0x08 clear
        self.assertTrue(valid.is_valid)
        self.assertFalse(invalid.is_valid)

    def test_sectors_recombined_from_minutes_and_ms(self):
        """The sector times are recombined from their minutes and milliseconds parts."""
        # s1 = 23.000s, s2 = 1:05.000 (minutes part = 1), s3 = 24.000s
        entry = _lap_entry(112000, 0x0F, sectors=[(0, 23000), (1, 5000), (0, 24000)])
        lap = self._one_lap_session(entry)
        self.assertEqual((lap.sector1_ms, lap.sector2_ms, lap.sector3_ms), (23000, 65000, 24000))
        self.assertEqual(lap.lap_time_ms, 112000)


class SetupHistoryTest(unittest.TestCase):
    """The player's setup is captured as an ordered history so mid-session garage changes
    resolve to the right lap in the detail view."""

    def test_setup_changes_recorded_as_history(self):
        stream = [session_pkt(1), participants_pkt(1), setup_pkt(1, front_wing=5)]
        stream += frames(1, 1, [0, 1500, 3000])
        stream += frames(1, 2, [0, 1500, 3000])
        stream += frames(1, 3, [0])                       # enter lap 3
        stream.append(setup_pkt(1, front_wing=9))         # setup changed while on lap 3
        stream += frames(1, 3, [1500, 3000])
        stream.append(sh_pkt(1, [_lap_entry(72000, 0x0F),
                                 _lap_entry(70000, 0x0F),
                                 _lap_entry(69000, 0x0F)]))
        (race,) = list(assemble(stream))
        self.assertEqual([(s.from_lap, s.setup.front_wing) for s in race.setup_history],
                         [(0, 5), (3, 9)])
        self.assertEqual(race.setup_for_lap(1).front_wing, 5)
        self.assertEqual(race.setup_for_lap(2).front_wing, 5)
        self.assertEqual(race.setup_for_lap(3).front_wing, 9)
    
    def test_identical_setup_not_duplicated(self):
        stream = [session_pkt(1), participants_pkt(1),
                  setup_pkt(1, front_wing=5), setup_pkt(1, front_wing=5)]
        stream += frames(1, 1, [0, 1500, 3000])
        stream += frames(1, 2, [0, 1500])
        stream.append(sh_pkt(1, [_lap_entry(80000, 0x0F), _lap_entry(0, 0x00)]))
        (race,) = list(assemble(stream))
        self.assertEqual(len(race.setup_history), 1)
    
    def test_garage_tuning_before_first_lap_resolves_to_chosen_setup(self):
        """Default + chosen setup both recorded on lap 1 (tuned in the garage before driving);
        every early lap must show the chosen setup, not the initial default that arrived first.
        Reproduces the Suzuka P1 bug where laps 1-3 showed the default."""
        stream = [session_pkt(1), participants_pkt(1)]
        stream += frames(1, 1, [0])                       # first join -> cur_lap = 1
        stream.append(setup_pkt(1, front_wing=5))         # initial/default, from_lap = 1
        stream.append(setup_pkt(1, front_wing=16))        # chosen in garage, from_lap = 1
        stream += frames(1, 1, [1500, 3000])
        stream += frames(1, 2, [0, 1500, 3000])
        stream += frames(1, 3, [0, 1500, 3000])
        stream += frames(1, 4, [0])                       # enter lap 4
        stream.append(setup_pkt(1, front_wing=18))        # tweak before lap 4, from_lap = 4
        stream += frames(1, 4, [1500, 3000])
        stream.append(sh_pkt(1, [_lap_entry(72000, 0x0F), _lap_entry(71000, 0x0F),
                                 _lap_entry(70000, 0x0F), _lap_entry(69000, 0x0F)]))
        (race,) = list(assemble(stream))
        # both same-lap snapshots are kept, in record order
        self.assertEqual([(s.from_lap, s.setup.front_wing) for s in race.setup_history],
                         [(1, 5), (1, 16), (4, 18)])
        self.assertEqual(race.setup_for_lap(1).front_wing, 16)   # chosen, not the 5 default
        self.assertEqual(race.setup_for_lap(2).front_wing, 16)
        self.assertEqual(race.setup_for_lap(3).front_wing, 16)
        self.assertEqual(race.setup_for_lap(4).front_wing, 18)   # later tweak

class TyreContextTest(unittest.TestCase):
    """A lap carries a tyre snapshot (compound/age from Car Status, wear from Car Damage)
    taken as the car crosses the line."""

    def test_tyre_context_snapshotted_at_lap_boundary(self):
        stream = [session_pkt(1), participants_pkt(1)]
        stream += frames(1, 1, [0, 1500, 3000])
        stream.append(status_pkt(1, compound=16, visual=16, age=2))
        stream.append(damage_pkt(1, wear=(5.0, 6.0, 7.0, 8.0)))
        stream += frames(1, 2, [0, 1500])                 # trailing, dropped (time 0)
        stream.append(sh_pkt(1, [_lap_entry(80000, 0x0F), _lap_entry(0, 0x00)]))
        (race,) = list(assemble(stream))
        context = race.laps[0].tyre_context
        self.assertIsNotNone(context)
        self.assertEqual(context.actual_compound, 16)
        self.assertEqual(context.age_laps, 2)
        self.assertEqual(context.wear, (5.0, 6.0, 7.0, 8.0))
        self.assertEqual(context.surface_temp, (90, 90, 90, 90))
        self.assertEqual(context.carcass_temp, (95, 95, 95, 95))

    def test_car_damage_snapshotted_at_lap_boundary(self):
        stream = [session_pkt(1), participants_pkt(1)]
        stream += frames(1, 1, [0, 1500, 3000])
        stream.append(status_pkt(1, compound=16, age=2))
        stream.append(damage_pkt(1, wear=(5.0, 6.0, 7.0, 8.0), tyre_damage=(2, 3, 4, 5),
                                 brakes=(1, 2, 3, 4), rear_wing_damage=30, floor_damage=10))
        stream += frames(1, 2, [0, 1500])
        stream.append(sh_pkt(1, [_lap_entry(80000, 0x0F), _lap_entry(0, 0x00)]))
        (race,) = list(assemble(stream))
        lap1 = race.laps[0]
        self.assertEqual(lap1.tyre_context.damage, (2, 3, 4, 5))
        self.assertEqual(lap1.damage.brakes, (1, 2, 3, 4))
        self.assertEqual(lap1.damage.rear_wing, 30)
        self.assertEqual(lap1.damage.floor, 10)
        self.assertFalse(lap1.damage.engine_blown)
        self.assertEqual(lap1.damage.brake_temp, (300, 300, 300, 300))
        self.assertEqual(lap1.damage.engine_temp, 110)


class LapContextTest(unittest.TestCase):
    """What the assembler reads out of Lap Data about the state the car was in.

    Every stream here is shaped like a real one: ``current_lap_num`` only advances when the line is
    crossed at the end of a *timed* lap, so an in-lap, a garage stop and the out-lap that follows
    all carry the lap number of the flying lap they lead into. That is why the garage frames of a
    practice run sit in the buffer of the lap they precede, and it is what the boundary flag reads.
    """

    def _practice_run_boundary(self):
        """P1: a flying lap, then in-lap + garage + out-lap under lap 2's number, then lap 2."""
        return [
            session_pkt(1, stype=SessionType.PRACTICE_1),
            participants_pkt(1),
            *frames(1, 1, [0, 2500, 5200], driver_status=DriverStatus.FLYING_LAP),
            # The counter does not advance at the line when the car is on an in-lap, in the pit
            # lane, or on an out-lap - so all three carry lap 2's number, ahead of lap 2's own run.
            *frames(1, 2, [5400, 5600], driver_status=DriverStatus.IN_LAP,
                    pit_status=PitStatus.PITTING, speed=60),
            *frames(1, 2, [220, 225], driver_status=DriverStatus.IN_GARAGE,
                    pit_status=PitStatus.PITTING, speed=60),
            *frames(1, 2, [280, 3000, 5600], driver_status=DriverStatus.OUT_LAP, speed=60),
            *frames(1, 2, [0, 2500, 5200], driver_status=DriverStatus.FLYING_LAP),
            sh_pkt(1, [_lap_entry(90000, 15), _lap_entry(91000, 15)]),
        ]

    def test_a_garage_visit_between_two_emitted_laps_is_flagged_on_the_later_one(self):
        result = next(assemble(self._practice_run_boundary()))
        by_number = {lap.lap_number: lap for lap in result.laps}
        self.assertEqual(sorted(by_number), [1, 2])
        self.assertFalse(by_number[1].preceded_by_garage)
        self.assertTrue(by_number[2].preceded_by_garage)

    def test_the_timed_lap_of_a_practice_run_is_a_flying_lap_not_an_in_or_out_lap(self):
        """The lap the driver pits on is never timed, so it is never emitted - measured across
        every capture here, where all 159 non-race laps read FLYING end to end."""
        result = next(assemble(self._practice_run_boundary()))
        for lap in result.laps:
            with self.subTest(lap=lap.lap_number):
                self.assertEqual(lap.driver_status, int(DriverStatus.FLYING_LAP))
                self.assertFalse(lap.is_out_lap)
                self.assertFalse(lap.is_in_lap)

    def test_a_normal_lap_to_lap_transition_flags_nothing(self):
        stream = [
            session_pkt(1), participants_pkt(1),
            *frames(1, 1, [0, 2500, 5000]),
            *frames(1, 2, [0, 2500, 5000]),
            sh_pkt(1, [_lap_entry(90000, 15), _lap_entry(89000, 15)]),
        ]
        result = next(assemble(stream))
        for lap in result.laps:
            with self.subTest(lap=lap.lap_number):
                self.assertFalse(lap.preceded_by_garage)
                self.assertFalse(lap.is_out_lap)
                self.assertFalse(lap.is_in_lap)
                self.assertEqual(lap.driver_status, int(DriverStatus.ON_TRACK))
                self.assertEqual(lap.pit_status, int(PitStatus.NONE))

    def test_a_race_pit_stop_flags_the_in_lap_and_the_out_lap_from_the_pit_lane_timer(self):
        """Lap 1 enters the pit lane before the line; lap 2 leaves it after. The stop itself is on
        lap 2 (``pit_status`` reaches IN_PIT_AREA), which is where the pit loss lands here."""
        stream = [
            session_pkt(1), participants_pkt(1),
            *frames(1, 1, [0, 2500, 4800]),
            *frames(1, 1, [5000, 5200], driver_status=DriverStatus.IN_LAP,
                    pit_status=PitStatus.PITTING, pit_lane_timer_active=1),
            *frames(1, 2, [10, 200], driver_status=DriverStatus.IN_LAP,
                    pit_status=PitStatus.IN_PIT_AREA, pit_lane_timer_active=1),
            *frames(1, 2, [300, 2500, 5000], driver_status=DriverStatus.OUT_LAP),
            *frames(1, 3, [0, 2500, 5000]),
            sh_pkt(1, [_lap_entry(92000, 15), _lap_entry(115000, 15), _lap_entry(89000, 15)]),
        ]
        by_number = {lap.lap_number: lap for lap in next(assemble(stream)).laps}
        self.assertTrue(by_number[1].is_in_lap)
        self.assertFalse(by_number[1].is_out_lap)
        self.assertTrue(by_number[2].is_out_lap)
        self.assertEqual(by_number[2].pit_status, int(PitStatus.IN_PIT_AREA))
        self.assertFalse(by_number[3].is_out_lap)
        # A race never reports the garage - the game says IN_PIT_AREA for a stop and keeps
        # IN_GARAGE for the garage proper, so this stays an *extra* run boundary, not a replacement.
        self.assertFalse(by_number[2].preceded_by_garage)

    def test_a_red_flag_restart_is_not_an_out_lap_however_the_status_reads(self):
        """Shanghai sprint lap 4 and Shanghai race lap 13, the two laps this rule turns on.

        After a red flag the game does not time the lap that drives out of the pit lane to the
        grid, so ``driver_status`` still reads OUT_LAP for 94-95% of the lap it *does* time - and
        that lap is a standing start from the grid box. The lane timer, which never ran, is right
        and the status is stale. ``lap_context`` marks the restart from ``red_flagged``.
        """
        stream = [
            session_pkt(1), participants_pkt(1),
            *frames(1, 1, [0, 2500, 5000]),
            *frames(1, 2, [0, 1000, 2000, 3000], driver_status=DriverStatus.OUT_LAP),
            *frames(1, 2, [4000], driver_status=DriverStatus.ON_TRACK),
            sh_pkt(1, [_lap_entry(90000, 15), _lap_entry(99000, 15)]),
        ]
        by_number = {lap.lap_number: lap for lap in next(assemble(stream)).laps}
        self.assertFalse(by_number[2].is_out_lap)
        self.assertFalse(by_number[1].is_out_lap)
        # the raw status is still stored, so nothing is lost by not acting on it here
        self.assertEqual(by_number[2].driver_status, int(DriverStatus.OUT_LAP))

    def test_only_the_lane_timer_makes_an_out_lap(self):
        """The same frames, with the lane timer running at the line: now it is an out-lap.

        Across all 470 emitted laps in this database the timer flags 15 and misses none - every
        real pit-lane exit carries a pit stop too.
        """
        stream = [
            session_pkt(1), participants_pkt(1),
            *frames(1, 1, [0, 2500, 5000]),
            *frames(1, 2, [0, 1000], driver_status=DriverStatus.OUT_LAP,
                    pit_status=PitStatus.IN_PIT_AREA, pit_lane_timer_active=1),
            *frames(1, 2, [2000, 3000, 4000], driver_status=DriverStatus.ON_TRACK),
            sh_pkt(1, [_lap_entry(90000, 15), _lap_entry(99000, 15)]),
        ]
        by_number = {lap.lap_number: lap for lap in next(assemble(stream)).laps}
        self.assertTrue(by_number[2].is_out_lap)

    def test_one_stale_out_lap_frame_does_not_label_the_lap_after_an_out_lap(self):
        """Sakhir race lap 15 and Shanghai race lap 11 each carry exactly one stale OUT_LAP frame.

        Nothing reads ``driver_status`` for the out-lap flag any more, so this cannot mislabel
        them - the test stays as the guard that it does not come back.
        """
        stream = [
            session_pkt(1), participants_pkt(1),
            *frames(1, 1, [0], driver_status=DriverStatus.OUT_LAP),
            *frames(1, 1, [1000, 2000, 3000, 4000, 5000]),
            sh_pkt(1, [_lap_entry(90000, 15)]),
        ]
        self.assertFalse(next(assemble(stream)).laps[0].is_out_lap)

    def test_a_session_whose_garage_frames_were_never_emitted_flags_nothing(self):
        """The garage sits in a buffer of its own that never became a lap - the trailing "driver
        parked at the end of the session" case. Nothing is invented for the laps that did emit."""
        stream = [
            session_pkt(1, stype=SessionType.PRACTICE_1), participants_pkt(1),
            *frames(1, 1, [0, 2500, 5000], driver_status=DriverStatus.FLYING_LAP),
            *frames(1, 2, [0, 2500, 5000], driver_status=DriverStatus.FLYING_LAP),
            *frames(1, 3, [100, 105], driver_status=DriverStatus.IN_GARAGE),   # no lap 3 time
            sh_pkt(1, [_lap_entry(90000, 15), _lap_entry(89500, 15), _lap_entry(0, 15)]),
        ]
        result = next(assemble(stream))
        self.assertEqual([lap.lap_number for lap in result.laps], [1, 2])
        self.assertFalse(any(lap.preceded_by_garage for lap in result.laps))

    def test_laps_from_a_stream_with_lap_data_always_carry_context(self):
        """``has_lap_context`` is what the charts test to choose stored truth over inference, so
        every lap the assembler emits has to satisfy it."""
        stream = [session_pkt(1), participants_pkt(1),
                  *frames(1, 1, [0, 2500, 5000]), sh_pkt(1, [_lap_entry(90000, 15)])]
        self.assertTrue(next(assemble(stream)).laps[0].has_lap_context)


class RaceControlTest(unittest.TestCase):
    """Safety car and red flag: session-wide state, attributed to the lap that was in progress."""

    def _stream(self, during_lap_two):
        """A two-lap race, with Session packets arriving *inside* each lap as the game sends them.

        The interleaving is the test as much as the assertion is: race control is attributed to the
        lap the frame join is filling, so a Session packet that lands between the last frame of one
        lap and the first frame of the next belongs to the earlier lap - the car has not crossed the
        line yet. Putting them mid-lap is what a real stream looks like at the game's 2 Hz.
        """
        return [
            session_pkt(1), participants_pkt(1),
            *frames(1, 1, [0, 2500]),
            session_pkt(1),                             # mid lap 1: nothing happening
            *frames(1, 1, [5000]),
            *frames(1, 2, [0]),
            during_lap_two,                             # mid lap 2
            *frames(1, 2, [2500, 5000]),
            sh_pkt(1, [_lap_entry(90000, 15), _lap_entry(130000, 15)]),
        ]

    def test_the_safety_car_lands_on_the_lap_it_was_deployed_in(self):
        stream = self._stream(session_pkt(1, safety_car=SafetyCarStatus.FULL))
        by_number = {lap.lap_number: lap for lap in next(assemble(stream)).laps}
        self.assertEqual(by_number[1].safety_car, int(SafetyCarStatus.NONE))
        self.assertEqual(by_number[2].safety_car, int(SafetyCarStatus.FULL))

    def test_a_deployment_beats_the_formation_lap_and_survives_going_green(self):
        """Race lap 1 sees the formation lap and then green; a lap that sees FULL and then green
        is still a safety-car lap. Whichever arrives second must not overwrite the deployment."""
        stream = [
            session_pkt(1, safety_car=SafetyCarStatus.FORMATION_LAP), participants_pkt(1),
            *frames(1, 1, [0]),
            session_pkt(1, safety_car=SafetyCarStatus.FORMATION_LAP),
            *frames(1, 1, [2500]),
            session_pkt(1, safety_car=SafetyCarStatus.NONE),     # green, still lap 1
            *frames(1, 1, [5000]),
            *frames(1, 2, [0]),
            session_pkt(1, safety_car=SafetyCarStatus.FULL),
            *frames(1, 2, [2500]),
            session_pkt(1, safety_car=SafetyCarStatus.NONE),     # returned, still lap 2
            *frames(1, 2, [5000]),
            sh_pkt(1, [_lap_entry(95000, 15), _lap_entry(130000, 15)]),
        ]
        by_number = {lap.lap_number: lap for lap in next(assemble(stream)).laps}
        self.assertEqual(by_number[1].safety_car, int(SafetyCarStatus.FORMATION_LAP))
        self.assertEqual(by_number[2].safety_car, int(SafetyCarStatus.FULL))

    def test_a_red_flag_is_the_counter_rising_not_the_counter_being_set(self):
        """The Shanghai sprint's ``num_red_flag_periods`` went 0 -> 1 on lap 2 and back to 0 on lap
        10, so only the rise can be trusted - reading the value would flag the whole restart."""
        stream = self._stream(session_pkt(1, red_flag_periods=1))
        by_number = {lap.lap_number: lap for lap in next(assemble(stream)).laps}
        self.assertFalse(by_number[1].red_flagged)
        self.assertTrue(by_number[2].red_flagged)

    def test_a_counter_that_falls_again_flags_nothing_further(self):
        stream = [
            session_pkt(1, red_flag_periods=1), participants_pkt(1),
            *frames(1, 1, [0]),
            session_pkt(1, red_flag_periods=1),
            *frames(1, 1, [2500, 5000]),
            *frames(1, 2, [0]),
            session_pkt(1, red_flag_periods=0),         # falls back - not a second red flag
            *frames(1, 2, [2500, 5000]),
            sh_pkt(1, [_lap_entry(90000, 15), _lap_entry(91000, 15)]),
        ]
        self.assertFalse(any(lap.red_flagged for lap in next(assemble(stream)).laps))

    def test_a_clean_race_flags_neither(self):
        result = next(assemble(self._stream(session_pkt(1))))
        for lap in result.laps:
            with self.subTest(lap=lap.lap_number):
                self.assertEqual(lap.safety_car, int(SafetyCarStatus.NONE))
                self.assertFalse(lap.red_flagged)


class MotionChannelsTest(unittest.TestCase):
    """Iteration 2b: Motion is carried forward into each sample (not a hard frame-join), so a
    stream with Motion gets position/g-force channels and one without still builds laps."""

    def test_stream_with_motion_populates_channels(self):
        pts = [(0, 10.0, 20.0, 0.5, -0.2),
               (1500, 11.0, 21.0, 1.5, 0.3),
               (3000, 12.0, 22.0, -0.4, 0.8)]
        stream = [session_pkt(1), participants_pkt(1)]
        stream += motion_frames(1, 1, pts)
        stream += frames(1, 2, [0, 1500])                 # trailing, dropped (time 0)
        stream.append(sh_pkt(1, [_lap_entry(80000, 0x0F), _lap_entry(0, 0x00)]))
        (race,) = list(assemble(stream))
        trace = race.laps[0].trace
        self.assertTrue(trace.has_motion)
        self.assertEqual(len(trace.pos_x), len(trace))    # parallel to the distance axis
        self.assertEqual(trace.pos_x.tolist(), [10.0, 11.0, 12.0])
        self.assertEqual(trace.pos_z.tolist(), [20.0, 21.0, 22.0])
        self.assertEqual(trace.g_lat.tolist(), [0.5, 1.5, -0.4])

    def test_stream_without_motion_still_builds(self):
        stream = [session_pkt(1), participants_pkt(1)]
        stream += frames(1, 1, [0, 1500, 3000])
        stream += frames(1, 2, [0, 1500])
        stream.append(sh_pkt(1, [_lap_entry(80000, 0x0F), _lap_entry(0, 0x00)]))
        (race,) = list(assemble(stream))
        trace = race.laps[0].trace
        self.assertIsNotNone(trace)                       # lap still built
        self.assertFalse(trace.has_motion)
        self.assertIsNone(trace.pos_x)

    def test_motion_carried_forward_not_joined(self):
        # Motion only on frame 1; the next two frames have no Motion packet of their own. A hard
        # 3-way join would drop them (no matching Motion) - carry-forward keeps every sample and
        # reuses the last position, proving the join is Lap+Telemetry only.
        stream = [session_pkt(1), participants_pkt(1)]
        stream += motion_frames(1, 1, [(0, 10.0, 20.0, 0.5, -0.2)])
        stream += frames(1, 1, [1500, 3000])              # no Motion on these frames
        stream += frames(1, 2, [0, 1500])
        stream.append(sh_pkt(1, [_lap_entry(80000, 0x0F), _lap_entry(0, 0x00)]))
        (race,) = list(assemble(stream))
        trace = race.laps[0].trace
        self.assertEqual(len(trace), 3)                   # all three frames joined, none dropped
        self.assertTrue(trace.has_motion)
        self.assertEqual(trace.pos_x.tolist(), [10.0, 10.0, 10.0])   # carried forward



if __name__ == "__main__":
    unittest.main()
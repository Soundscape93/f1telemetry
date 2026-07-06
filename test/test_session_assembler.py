"""Test cases for the session assembler, which takes a stream of packets and produces
one ``SessionResult`` per session UID. The assembler is responsible for joining the player's
lap traces, the player's setup, and the final classification into a single deliverable.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from f1telemetry.src.protocol.enums import Formula, PacketId, SessionType, Weather
from f1telemetry.src.session.assembler import assemble


def _hdr(pid, uid, frame=0, player=0):
    """Build a fake packet header for testing."""
    return SimpleNamespace(packet_id=pid, session_uid=uid, frame_identifier=frame,
                           packet_format=2025, player_car_index=player)


def session_pkt(uid, stype=SessionType.RACE, laps=5):
    """Build a fake session packet for testing."""
    return SimpleNamespace(
        header=_hdr(PacketId.SESSION, uid),
        season_link_identifier=uid, weekend_link_identifier=uid, session_link_identifier=uid,
        track_id=7, session_type=int(stype), formula=int(Formula.F1_MODERN),
        weather=int(Weather.CLEAR), game_mode=28, total_laps=laps,
        num_sessions_in_weekend=0, weekend_structure=[0] * 12)


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
                           lap_history_data=entries)


_frame = [0]
def frames(uid, lap_num, distances, player=0):
    """Build a sequence of fake Lap Data + Car Telemetry packets for testing.
    Each distance in `distances` is a separate frame, and the frame identifier is incremented for each frame.
    The lap number is constant for all frames, and the session UID is constant"""
    out = []
    for d in distances:
        _frame[0] += 1
        f = _frame[0]
        out.append(SimpleNamespace(header=_hdr(PacketId.LAP_DATA, uid, frame=f, player=player),
                                   lap_data=[SimpleNamespace(current_lap_num=lap_num, lap_distance=d)]))
        out.append(SimpleNamespace(header=_hdr(PacketId.CAR_TELEMETRY, uid, frame=f, player=player),
                                   car_telemetry_data=[SimpleNamespace(
                                       speed=200, throttle=1.0, brake=0.0, steer=0.0,
                                       gear=7, engine_rpm=10000, drs=0)]))
    return out


def status_pkt(uid, compound=16, visual=16, age=1, player=0):
    """Fake Car Status packet: the player's tyre compound + age (and zeroed ERS)."""
    return SimpleNamespace(
        header=_hdr(PacketId.CAR_STATUS, uid, player=player),
        car_status_data=[SimpleNamespace(
            actual_tyre_compound=compound, visual_tyre_compound=visual,
            tyres_age_laps=age, ers_store_energy=0.0, ers_deploy_mode=0)])


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
    """A lap that starts far from the line is not emitted, even if Session History has a time for it,"""
    def test_lap_starting_far_from_line_is_not_emitted(self):
        """The first lap starts far from the line, so it is not emitted, even though Session History has a time for it."""
        stream = [session_pkt(1), participants_pkt(1)]
        stream += frames(1, 1, [250, 1500, 3000])
        stream += frames(1, 2, [5, 1500, 3000])           # trailing, starts near line
        stream.append(sh_pkt(1, [_lap_entry(90000, 0x0F),
                                 _lap_entry(85000, 0x0F)]))
        (race,) = list(assemble(stream))
        self.assertEqual([l.lap_number for l in race.laps], [2])


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


if __name__ == "__main__":
    unittest.main()
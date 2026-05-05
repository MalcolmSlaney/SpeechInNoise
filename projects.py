from audio import AudioDB, AudioOutputBP
from storage import relpath
import pathlib, warnings

class AudioSpec:
    trials_table = "audio_trials"
    results_table = "audio_results"
    asr_table = "audio_asr"
    annotations_table = "audio_annotations"

    def validate(self):
        """Check to make sure all needed audio files exist on disk."""
        files = self.queryall(
                f"SELECT project, filename FROM {__class__.trials_table}")
        if not files:
            return
        missing = []
        for project, file in files:
            path = pathlib.Path(relpath("static", "audio", file))
            if not path.exists():
                missing.append(path)
        if not missing:
            return
        common = [all(i[0] == j for j in i) for i in zip(*map(str, missing))]
        pre = str(missing[0])[:min(range(len(common)), key=lambda x: common[x])]
        eg = str(missing[0])[len(pre):]
        warnings.warn(f"missing {len(missing)} files at {pre}[...] (eg {eg})")

class QuickSpec(AudioSpec):
    audio_files = relpath("metadata/quicksin_transcript.csv")
    project_key = "quick"

class QuickDB(QuickSpec, AudioDB):
    csv_keys = (
        "active", "lang", "trial_number", "level_number", "snr", "filename",
        "answer")

    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class QuickBP(QuickSpec, AudioOutputBP):
    audio_keys = (
        "id", "snr", "lang", "level_number", "trial_number", "filename",
        "answer")
    audio_done = [1, 0, "--", 0, 1, "", 1]

    def __init__(self, db, name="quick", url_prefix="/quick"):
        super().__init__(db, name, url_prefix)

class Qs3Spec(AudioSpec):
    audio_files = relpath("metadata/qs3db_transcript.csv")
    project_key = "qs3"

class Qs3DB(Qs3Spec, AudioDB):
    csv_keys = (
        "active", "lang", "trial_number", "level_number", "snr", "filename",
        "answer")

    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class Qs3BP(Qs3Spec, AudioOutputBP):
    audio_keys = (
        "id", "snr", "lang", "level_number", "trial_number", "filename",
        "answer")
    audio_done = [1, 0, "--", 0, 1, "", 1]

    def __init__(self, db, name="qs3", url_prefix="/qs3"):
        super().__init__(db, name, url_prefix)

class Nu6Spec(AudioSpec):
    audio_files = relpath("metadata/nu6_transcript.csv")
    project_key = "nu6"

class Nu6DB(Nu6Spec, AudioDB):
    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class Nu6BP(Nu6Spec, AudioOutputBP):
    def __init__(self, db, name="nu6", url_prefix="/nu6"):
        super().__init__(db, name, url_prefix)

# AzBio with 10dB SNR
class AzBioSpec(AudioSpec):
    audio_files = relpath("metadata/azbio_transcript.csv")
    project_key = "azbio"

class AzBioDB(AzBioSpec, AudioDB):
    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class AzBioBP(AzBioSpec, AudioOutputBP):
    def __init__(self, db, name="azbio", url_prefix="/azbio"):
        super().__init__(db, name, url_prefix)

# AzBio in Quiet
class AzBioQuietSpec(AudioSpec):
    audio_files = relpath("metadata/azbio_quiet_transcript.csv")
    project_key = "azbio_quiet"

class AzBioQuietDB(AzBioQuietSpec, AudioDB):
    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class AzBioQuietBP(AzBioQuietSpec, AudioOutputBP):
    def __init__(self, db, name="azbio_quiet", url_prefix="/azbio_quiet"):
        super().__init__(db, name, url_prefix)

class CncSpec(AudioSpec):
    audio_files = relpath("metadata/cnc_transcript.csv")
    project_key = "cnc"

class CncDB(CncSpec, AudioDB):
    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class CncBP(CncSpec, AudioOutputBP):
    def __init__(self, db, name="cnc", url_prefix="/cnc"):
        super().__init__(db, name, url_prefix)

class WinSpec(AudioSpec):
    audio_files = relpath("metadata/win_transcript.csv")
    project_key = "win"

class WinDB(WinSpec, AudioDB):
    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class WinBP(WinSpec, AudioOutputBP):
    def __init__(self, db, name="win", url_prefix="/win"):
        super().__init__(db, name, url_prefix)

# Spanish
# AzBio in Spanish with 10dB(?) SNR
class AzBioSpanishSpec(AudioSpec):
    audio_files = relpath("metadata/azbio_spanish_transcript.csv")
    project_key = "azbio_spanish"

class AzBioSpanishDB(AzBioSpanishSpec, AudioDB):
    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class AzBioSpanishBP(AzBioSpanishSpec, AudioOutputBP):
    def __init__(self, db, name="azbio_spanish", url_prefix="/azbio_spanish"):
        super().__init__(db, name, url_prefix)

# AzBio in Spanish in Quiet
class AzBioSpanishQuietSpec(AudioSpec):
    audio_files = relpath("metadata/azbio_spanish_quiet_transcript.csv")
    project_key = "azbio_spanish_quiet"

class AzBioSpanishQuietDB(AzBioSpanishQuietSpec, AudioDB):
    def db_init_hook(self):
        super().db_init_hook()
        self.parse_csv(__class__)

class AzBioSpanishQuietBP(AzBioSpanishQuietSpec, AudioOutputBP):
    def __init__(self, db, name="azbio_spanish_quiet", url_prefix="/azbio_spanish_quiet"):
        super().__init__(db, name, url_prefix)
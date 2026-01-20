import glob
import os
import subprocess
from typing import Dict, List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import ArrayLike, NDArray
import scipy

from absl import app
from absl import flags


def read_mp4(audio_url, 
             tmp_wav_file: str = '/tmp/audio.wav') -> Tuple[float, NDArray]:
  subprocess.run(['ffmpeg', '-loglevel', 'quiet', '-i', audio_url, 
                  '-acodec', 'pcm_s16le', '-ar', '16000', tmp_wav_file])

  if not os.path.exists(tmp_wav_file):
    print(f'FFMPEG did not produce an audio file for {audio_url}.')
    return 0, None
  rate, data = scipy.io.wavfile.read(tmp_wav_file)

  os.remove(tmp_wav_file)
  return rate, data


def frame_energy(data: NDArray) -> float:
  """Calculates the energy of an audio frame."""
  
  frame_size = 1024  # 64ms at 16kHz
  hop_length = 512   # 32ms at 16kHz

  num_samples = len(data)
  num_frames = 1 + int(np.floor((num_samples - frame_size) / hop_length))

  energy_per_frame = []

  for i in range(num_frames):
    start_sample = i * hop_length
    end_sample = start_sample + frame_size
    frame = data[start_sample:end_sample]
    energy = np.sum(frame.astype(float)**2)
    energy_per_frame.append(energy)
  return np.asarray(energy_per_frame), hop_length


def endpoint_audio(audio_data: NDArray,
                   energy_per_frame: NDArray, fs: float, hop_length: int, 
                   energy_threshold: float = 0.0,
                   min_width: int = 5) -> NDArray:
  if energy_threshold <= 0.0:
    energy_threshold = np.max(energy_per_frame)/ 10.0  
  above_threshold = energy_per_frame > energy_threshold
  locs = np.nonzero(above_threshold)[0]
  # print(locs)
  for loc in locs:
    # print(loc, all(energy_per_frame[loc:loc+min_width] > energy_threshold))
    if all(energy_per_frame[loc:loc+min_width] > energy_threshold):
      loc = max(loc-20, 0)
      plt.plot(energy_per_frame)
      plt.axhline(energy_threshold, ls='--')
      plt.axvline(loc, ls='--')
      return audio_data[loc*hop_length:]
  return audio_data


def process_all_files(directory: str = '.', pattern='sin*', 
                      output_suffix: str = '.wav',
                      skip_suffixes: Tuple[str] = ('.mp4', )):
  all_files = glob.glob(os.path.join(directory, pattern))
  for file in all_files:
    if file.endswith(output_suffix):
      # Already processed.  Skip now.
      continue
    if any([file.endswith(s) for s in skip_suffixes]):
      continue
    rate, audio_data = read_mp4(file)
    if audio_data is None:
      continue
    energy_per_frame, hop_length = frame_energy(audio_data)
    new_audio = endpoint_audio(audio_data, energy_per_frame, rate, hop_length)
    print(f'{file}: Original audio {audio_data.shape[0]/rate}s, '
          f'new size {new_audio.shape[0]/rate}s')

    output_wav_filename = file + output_suffix
    scipy.io.wavfile.write(output_wav_filename, rate, new_audio)


FLAGS = flags.FLAGS
flags.DEFINE_string('directory', 'uploads',
                    'Where to find the audio files to process')

def main(argv):
  """Main entry point."""
  process_all_files(FLAGS.directory)

if __name__ == '__main__':
  app.run(main) 

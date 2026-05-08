import os
import numpy as np

class AWGdata():
    def __init__(self, file):
        with open(file, "r") as lines:
            starting_line = '----------------------------------------------------------'
            self.channels = ['T[s]']
            self.spectrum = None
            self.H = None
            self.T = None
            self.h = None
            self.sample_freq = None
            self.tf = None

            reading_heading = True
            for i, line in enumerate(lines):
                line = line.rstrip()
                if reading_heading:
                    if line.startswith('Spectrum:'):
                        self.spectrum = line.split(' ')[-1]
                    if line.startswith('Wave height:'):
                        self.H = float(line.split(' ')[-2])
                    if line.startswith('Wave period:'):
                        self.T = float(line.split(' ')[-2])
                    if line.startswith('Water depth:'):
                        self.h = float(line.split(' ')[-2])
                    if line.startswith('Sample frequency:'):
                        self.sample_freq = float(line.split(' ')[-2])
                    if line.startswith('Sample duration:'):
                        self.tf = float(line.split(' ')[-2])
                    if line.startswith('Physical Connection:'):
                        self.channels.append(line.split(': ')[-1])
                    if line.startswith(starting_line):
                        data_line = True
                        data_line0 = i + 2
        self.DATA = np.genfromtxt(file, delimiter=None, skip_header=data_line0)
        self.N_samples = self.DATA.shape[0]
        self.sample_T = 1/self.sample_freq
        self.TIMES = np.linspace(0, self.tf, self.N_samples)
        self.DATA = np.column_stack([self.TIMES.transpose(), self.DATA])

def read_plain_data_file(filename):
    with open(filename, 'r', encoding='UTF-8') as file:
        skip = 0
        try:
            line = file.readline()
            header = line.strip().split('\t')
        except:
            skip = 1
        data = np.loadtxt(file, delimiter=None, skiprows=skip)
    return data, header

def read_data_file(file):
    file_name, file_extension = os.path.splitext(file)
    if file_extension == '.awg':
        awg_data = AWGdata(file)
        return awg_data.DATA, awg_data.channels
    else:
        return read_plain_data_file(file)

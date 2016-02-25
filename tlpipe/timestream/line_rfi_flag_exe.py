"""Spectrum line RFI flagging by throwing out values exceed the given threshold."""

try:
    import cPickle as pickle
except ImportError:
    import pickle

import numpy as np
import h5py

from tlpipe.utils import mpiutil
from tlpipe.core.base_exe import Base
from tlpipe.utils.path_util import input_path, output_path


# Define a dictionary with keys the names of parameters to be read from
# file and values the defaults.
params_init = {
               'nprocs': mpiutil.size, # number of processes to run this module
               'aprocs': range(mpiutil.size), # list of active process rank no.
               'input_file': 'data_phs2src.hdf5',
               'output_file': 'data_line_rfi.hdf5',
               'imaginary_only': False, # rfi flag in imaginary part if True
               'threshold': 0.1,
               'fill0': False, # fill 0 for rfi value, else fill nan
               'extra_history': '',
              }
prefix = 'lr_'



class RfiFlag(Base):
    """Spectrum line RFI flagging by throwing out values exceed the given threshold."""

    def __init__(self, parameter_file_or_dict=None, feedback=2):

        super(RfiFlag, self).__init__(parameter_file_or_dict, params_init, prefix, feedback)

    def execute(self):

        input_file = input_path(self.params['input_file'])
        output_file = output_path(self.params['output_file'])
        imaginary_only = self.params['imaginary_only']
        threshold = self.params['threshold']
        fill0 = self.params['fill0']

        with h5py.File(input_file, 'r') as f:
            dset = f['data']
            data_shp = dset.shape
            data_type = dset.dtype
            ants = dset.attrs['ants']
            freq = dset.attrs['freq']
            # ts = f['time'] # Julian date for data in this file only

            nt = data_shp[0]
            npol = data_shp[2]
            nfreq = len(freq)

            nants = len(ants)
            bls = [(ants[i], ants[j]) for i in range(nants) for j in range(i, nants)]
            nbls = len(bls)

            lbls, sbl, ebl = mpiutil.split_local(nbls)
            local_bls = range(sbl, ebl)

            local_data = dset[:, sbl:ebl, :, :]


        if mpiutil.rank0:
            data_rfi_flag = np.zeros((nt, nbls, npol, nfreq), dtype=data_type) # save data that have rfi flagged
        else:
            data_rfi_flag= None

        for pol_ind in range(npol):
            for bi, bl_ind in enumerate(local_bls): # mpi among bls

                data_slice = local_data[:, bi, pol_ind, :].copy()
                if imaginary_only:
                    # rfi flag in imaginary part only
                    tm = np.mean(np.abs(np.concatenate((data_slice[:10], data_slice[-10:])).imag), axis=0) # time mean
                else:
                    # rfi flag in real and imaginary part
                    tm = np.mean(np.abs(np.concatenate((data_slice[:10], data_slice[-10:]))), axis=0) # time mean

                val = np.sort(tm)[int((1 - threshold) * len(tm))]
                inds = np.where(tm > val)[0]
                # rfi flag
                if fill0:
                    local_data[:, bi, pol_ind, inds] = 0
                else:
                    local_data[:, bi, pol_ind, inds] = complex(np.nan, np.nan)

        # Gather data in separate processes
        mpiutil.gather_local(data_rfi_flag, local_data, (0, sbl, 0, 0), root=0, comm=self.comm)


        # save data rfi flagged
        if mpiutil.rank0:
            with h5py.File(output_file, 'w') as f:
                dset = f.create_dataset('data', data=data_rfi_flag)
                # copy metadata from input file
                with h5py.File(input_file, 'r') as fin:
                    f.create_dataset('time', data=fin['time'])
                    for attrs_name, attrs_value in fin['data'].attrs.iteritems():
                        dset.attrs[attrs_name] = attrs_value
                # update some attrs
                dset.attrs['history'] = dset.attrs['history'] + self.history
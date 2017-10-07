from netCDF4 import Dataset
import numpy as np
import time, cPickle, sys, os
from mpi4py import MPI
from write_diag import write_diag
import f90nml

# mpirun -np 64 /contrib/anaconda/2.3.0/bin/python psop_fv3_mpi.py

comm = MPI.COMM_WORLD
nanals = comm.size
nmem = comm.rank + 1
member = 'mem%03i' % nmem

# set parameters.
rlapse_stdatm = 0.0065
grav = 9.80665; rd = 287.05; cp = 1004.6; rv=461.5
kap1 = (rd/cp)+1.0
kapr = (cp/rd)

# read from fortran namelist.
nml = f90nml.read('psop.nml')
res = nml['psop_nml']['res']
date = nml['psop_nml']['date']
ntimes = nml['psop_nml']['ntimes']
fhmin = nml['psop_nml']['fhmin']
fhout = nml['psop_nml']['fhout']
nlev = nml['psop_nml']['nlev']
obsfile = nml['psop_nml']['obsfile']
picklefile = nml['psop_nml']['meshfile']
if nml['psop_nml'].has_key('zthresh'):
    zthresh = nml['psop_nml']['zthresh']
else:
    zthresh = 1000.
if nml['psop_nml'].has_key('delz_const'):
    delz_const = nml['psop_nml']['zthresh']
else:
    delz_const = 0.001
datapath = os.path.join(nml['psop_nml']['datapath'],member)

def preduce(ps,tpress,t,zmodel,zob,rlapse):
# compute MAPS pressure reduction from model to station elevation
# See Benjamin and Miller (1990, MWR, p. 2100)
# uses 'effective' surface temperature extrapolated
# from virtual temp (tv) at tpress mb
# using specified lapse rate.
# Avoids diurnal cycle effects that effect 'real' surface temp.
# ps - surface pressure to reduce.
# t - virtual temp. at pressure tpress.
# zmodel - model orographic height.
# zob - station height
# rlapse - lapse rate (positive - usually US standard atmosphere)
   alpha = rd*rlapse/grav
   # from Benjamin and Miller (http://dx.doi.org/10.1175/1520-0493(1990)118<2099:AASLPR>2.0.CO;2) 
   t0 = t*(ps/tpress)**alpha # eqn 4 from B&M
   preduce = ps*((t0 + rlapse*(zob-zmodel))/t0)**(1./alpha) # eqn 1 from B&M
   return preduce

def palt(ps,zs):
# compute QNH altimeter setting (in mb) given ps (in mb), zs (in m).
# see WAF, Sept 1998, p 833-850 (Pauley) section 2c
   t0 = 288.15; p0 = 1013.25
   alpha = rd*rlapse_stdatm/grav
   palt = ps*(1.+(rlapse_stdatm*zs/t0)*(p0/ps)**alpha)**(1./alpha)
   return palt


# read pre-computed and pickled stripack triangulation.

tri = cPickle.load(open(picklefile,'rb'))

# read in ps obs.

olats = []; olons = []; obs = []; zobs = []; times = []; stdevorig = []; bias = []
stattype = []; statinfo = []
for line in open(obsfile):
    statid = line[0:19]
    statname = line[87:117]
    obid = line[118:131]
#   skip first 19 chars in line (contains ob identification string)
    line = line[20:]
    stattype.append(int(line[0:3]))
    #statinfo.append(statid+' '+statname+' '+obid)
    statinfo.append(obid[-8:]) # only 8 chars allowed
    olons.append(float(line[6:13]))
    olats.append(float(line[14:20]))
    zobs.append(float(line[21:26]))
    times.append(float(line[28:33]))
    obs.append(float(line[35:41]))
    bias.append(float(line[51:61]))
    stdevorig.append(float(line[61:67]))
olons = np.radians(np.array(olons))
olats = np.radians(np.array(olats))
obs = np.array(obs); times = np.array(times); zobs = np.array(zobs)
bias = np.array(bias); stdevorig = np.array(stdevorig)
bias = np.where(bias < 1.e20, bias, 0)
stattype = np.array(stattype)
statinfo2 = np.array(statinfo, dtype='c').T
nobs = len(obs)
iuseob = np.zeros(nobs, np.int8)
iuseob = np.where(np.logical_and(times >= -3, times <= 3), 1, 0)
if comm.rank == 0: print nobs-iuseob.sum(),' obs have invalid time'
altob = palt(obs, zobs)
nobs_before = iuseob.sum()
iuseob = np.where(np.logical_and(iuseob, np.logical_and(altob >= 850, altob <= 1090)), 1, 0)
if comm.rank == 0: print nobs_before-iuseob.sum(),' obs have out of range altimeter setting'

# read data from history files.

t1 = time.clock()
psmodel = np.empty((ntimes,6,res,res),np.float64)
tmodel = np.empty((ntimes,6,res,res),np.float64)
pmodel = np.empty((ntimes,6,res,res),np.float64)
zsmodel = np.empty((6,res,res),np.float64)
nlevs = None
for ntile in range(1,7,1):
    datafile = '%s/fv3_history.tile%s.nc'% (datapath,ntile)
    try:
        nc = Dataset(datafile)
    except:
        raise IOError('cannot open %s' % datafile)
    if nlevs is None:
        nlevs = len(nc.dimensions['pfull'])
    for ntime in range(0,ntimes): # skip first time
        psmodel[ntime,ntile-1,:,:] = 0.01*nc['ps'][ntime]
        tmodel[ntime,ntile-1,:,:] = nc['temp'][ntime,nlevs-nlev,:,:] +\
        (rv/rd-1.0)*nc['sphum'][ntime,nlevs-nlev,:,:]
        pmodel[ntime,ntile-1,:,:] = 0.01*nc['pfhy'][ntime,nlevs-nlev,:,:]
    zsmodel[ntile-1,:,:] = nc['zs'][:]
psmodel = psmodel.reshape((ntimes,6*res*res))
zsmodel = zsmodel.reshape((6*res*res))
tmodel = tmodel.reshape((ntimes,6*res*res))
pmodel = pmodel.reshape((ntimes,6*res*res))
if comm.rank == 0:
    print 'min/max ps %s' % member,psmodel.min(), psmodel.max()
    print 'min/max zs %s' % member,zsmodel.min(), zsmodel.max()
    print 'min/max t at level %s %s' % (nlev,member), tmodel.min(), tmodel.max()
    print 'min/max p at level %s %s' % (nlev,member), pmodel.min(), pmodel.max()
    print 'read data from history files took ',time.clock()-t1,' secs'
    
# interpolate to ob locations.
t1 = time.clock()
zsmodel_interp = tri.interp_linear(olons,olats,zsmodel)
psmodel_interp = np.empty((ntimes,nobs),np.float64)
tmodel_interp = np.empty((ntimes,nobs),np.float64)
pmodel_interp = np.empty((ntimes,nobs),np.float64)
for ntime in range(ntimes):
    psmodel_interp[ntime] = tri.interp_linear(olons,olats,psmodel[ntime])
    tmodel_interp[ntime] = tri.interp_linear(olons,olats,tmodel[ntime])
    pmodel_interp[ntime] = tri.interp_linear(olons,olats,pmodel[ntime])
# linear interpolation in time.
dtob = (fhmin+times)/fhout
idtob  = dtob.astype(np.int)
idtobp = idtob+1
idtobp = np.minimum(idtobp,ntimes-1)
delt = dtob - idtob.astype(np.float64)
anal_ob = np.empty(nobs, np.float64)
anal_obp = np.empty(nobs, np.float64)
anal_obt = np.empty(nobs, np.float64)
# assume lapse rate is constant, equal to standard atmosphere value.
anal_oblapse = rlapse_stdatm*np.ones(nobs, np.float64)
for nob in range(nobs):
    anal_ob[nob] = (1.-delt[nob])*psmodel_interp[idtob[nob],nob] + delt[nob]*psmodel_interp[idtobp[nob],nob]
    anal_obp[nob] = (1.-delt[nob])*pmodel_interp[idtob[nob],nob] + delt[nob]*pmodel_interp[idtobp[nob],nob]
    anal_obt[nob] = (1.-delt[nob])*tmodel_interp[idtob[nob],nob] + delt[nob]*tmodel_interp[idtobp[nob],nob]

# adjust interpolated model forecast pressure to station height
anal_ob = preduce(anal_ob, anal_obp, anal_obt, zobs, zsmodel_interp, anal_oblapse)
if comm.rank == 0: print 'interpolation %s points took' % nobs,time.clock()-t1,' secs'
#if comm.rank == 0: print 'min/max interpolated field:',psmodel_interp.min(), psmodel_interp.max()

zdiff = np.abs(zobs - zsmodel_interp)
# adjust ob error based on diff between station and model height.
# (GSI uses 0.005 for delz_const)
stdev = stdevorig + delz_const*zdiff

nobs_before = iuseob.sum()
iuseob = np.where(np.logical_and(iuseob, zdiff < zthresh), 1, 0)
if comm.rank == 0: print nobs_before-iuseob.sum(),' obs have too large an orography mismatch'

# compute ensemble mean on root task.
ensmean_ob = np.zeros(anal_ob.shape, anal_ob.dtype)
comm.Reduce(anal_ob, ensmean_ob, op=MPI.SUM, root=0)

#ominusf = (obs-anal_ob)[iuseob.astype(np.bool)]
#print ominusf.shape,iuseob.sum()
#print '%s rms O-F' % member,np.sqrt((ominusf**2).mean())

olons = np.degrees(olons); olats = np.degrees(olats)
if comm.rank == 0:
    # write out text file.
    ensmean_ob = ensmean_ob/nanals
    ominusf = (obs-ensmean_ob)[iuseob.astype(np.bool)]
    #print ominusf.shape,iuseob.sum()
    print 'ens mean rms O-F for %s obs' % iuseob.sum(),np.sqrt((ominusf**2).mean())
    
    fout = open('psobs_prior.txt','w')
    for nob in range(nobs):
        if stdev[nob] > 99.99: stdev[nob] = 99.99
        stringout = '%-64s %3i %7.2f %6.2f %5i %5i %6.2f %7.1f %7.1f %5.2f %5.2f %1i\n' % (statinfo[nob],stattype[nob],olons[nob],olats[nob],zobs[nob],np.rint(zsmodel_interp[nob]),times[nob],obs[nob],ensmean_ob[nob],stdevorig[nob],stdev[nob],iuseob[nob])
        fout.write(stringout)
    fout.close()

stdev = np.where(iuseob == 0, 1.e10, stdev)
idate = int(date)
diagfile = "diag_conv_ges.%s_mem%03i" % (idate,nmem)
write_diag(diagfile,comm.rank,idate,statinfo2,stattype,olons,olats,times,obs,zobs,stdev,stdevorig,anal_ob,zsmodel_interp,bias)
if comm.rank == 0:
    diagfile = "diag_conv_ges.%s_ensmean" % idate
    write_diag(diagfile,comm.rank,idate,statinfo2,stattype,olons,olats,times,obs,zobs,stdev,stdevorig,ensmean_ob,zsmodel_interp,bias)

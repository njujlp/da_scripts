# need envars:  analdate, datapath2, hsidir, save_hpss, save_hpss_subset, POSTPROC, npefiles

exitstat=0
module load hpss
env
hsi ls -l $hsidir
hsi mkdir ${hsidir}/
cd ${datapath2}

if  [ $save_hpss = "true" ]; then
   echo "htar fgens, fgens2"
   /bin/rm -rf gsitmp*
   /bin/rm -rf sanl*mem*
   cd fgens # fgens has FV3 restart files
   htar -cvf ${hsidir}/${analdate}_fgens.tar * &
   cd ../fgens2 # fgens2 has nemsio files
   htar -cvf ${hsidir}/${analdate}_fgens2.tar * &
   cd ..
   wait
   #if [ $npefiles = '0' ]; then
   #   cd diagens
   #   echo "htar diagens"
   #   htar -cvf ${hsidir}/diag_conv_${analdate}.tar * 
   #   cd ..
   #fi
else
   echo 'not saving data to hpps, just clean up...'
fi

hsi ls -l ${hsidir}/${analdate}_fgens.tar
if [  $? -eq 0 ] || [ $save_hpss != "true" ]; then
   echo "hsi fgens done or not requested, deleting data..."
   /bin/rm -rf fgens
else
   if [ $save_hpss == 'true']; then
      echo "hsi fgens failed ${analdate}..."
      exitstat=1
   fi
fi
hsi ls -l ${hsidir}/${analdate}_fgens2.tar
if [  $? -eq 0 ] || [ $save_hpss != "true" ]; then
   echo "hsi fgens2 done or not requested, deleting data..."
   /bin/rm -rf fgens2
else
   if [ $save_hpss == 'true']; then
      echo "hsi fgens2 failed ${analdate}..."
      exitstat=1
   fi
fi

#if  [ $npefiles == "0" ]; then
#hsi ls -l ${hsidir}/diag_conv_${analdate}.tar
#if [  $? -eq 0 ] || [ $save_hpss != "true" ]; then
#   echo "hsi diag finished, deleting data..."
#   /bin/rm -rf diagens
#else
#   echo "hsi diagens failed..."
#   exit 3
#fi
#fi

# remove unwanted files and directories.
cd $datapath2
nanal=0 
while [ $nanal -le $nanals ]; do
   if [ $nanal -eq 0 ]; then
      charnanal="ensmean"
   else
      charnanal="mem"`printf %03i $nanal`
   fi
   # remove GSI temp dirs
   /bin/rm -rf gsitmp_${charnanal} 
   # remove remaining 'every member' files
   if [ $nanal -gt 0 ]; then
      /bin/rm -rf *${charnanal}*
   fi
   nanal=$[$nanal+1]
done 
/bin/rm -rf *ens

# now save what's left to HPSS
if  [ $save_hpss_subset = "true" ]; then
   cd ${datapath2}
   cd ..
   # exclude long forecast directory
   htar -cvf ${hsidir}/${analdate}_subset.tar ${analdate}  --exclude=./${analdate}/longfcst
   # remove cris,iasi airs diag files to save more space
   #/bin/rm -f ${analdate}/diag*cris* ${analdate}/diag*airs* ${analdate}/diag*iasi*
fi
hsi ls -l ${hsidir}/${analdate}_subset.tar
if [  $? -eq 0 ]; then
   echo "hsi subset failed ${analdate}..."
   exit 1
fi

exit $exitstat

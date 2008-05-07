#!/bin/bash
source run.lib || exit 101

trap abort 0 1 2 3 15
export MY_JOBID="$1"
export MY_LANDINGZONE="`pwd`"
export MY_MARKER="$MY_LANDINGZONE/RUNNING.$$"
export MY_SCRATCH="`getscratch`"
shift

# Print job informations
echo -e "JOBID=$MY_JOBID\ngrid-control running on: `hostname -f; uname -a; cat /etc/redhat-release`"
checkdir "Start directory" "$MY_LANDINGZONE"
checkdir "Scratch directory" "$MY_SCRATCH"

echo $$ > $MY_MARKER
if [ -n "$(getrealdir $MY_SCRATCH | grep $(getrealdir $MY_LANDINGZONE))" ]; then
	echo "\$MY_SCRATCH is a subdirectory of \$MY_LANDINGZONE"
	# Landing zone: Used space < 5Gb && Free space > 1Gb (using limits on the scratch directory)
	monitordirlimits "SCRATCH" $MY_LANDINGZONE &
else
	# Landing zone: Used space < 50Mb && Free space > 100Mb
	monitordirlimits "LANDINGZONE" "$MY_LANDINGZONE" &
	# Landing zone: Used space < 5Gb && Free space > 1Gb
	monitordirlimits "SCRATCH" "$MY_SCRATCH" &
fi

checkfile "$MY_LANDINGZONE/sandbox.tar.gz"
echo "Unpacking environment"
tar xvfz "$MY_LANDINGZONE/sandbox.tar.gz" -C "$MY_SCRATCH" || fail 105

checkfile "$MY_SCRATCH/_config.sh"
source "$MY_SCRATCH/_config.sh"

checkvar MY_RUNTIME

# Copy files from the SE
if [ -n "$SE_INPUT_FILES" ]; then
	se_copy "$SE_PATH" "file://$MY_SCRATCH" "$SE_INPUT_FILES"
fi

# Execute program
echo "==========================="
cd $MY_SCRATCH
eval "$MY_RUNTIME" &
MY_RUNID=$!
echo $MY_RUNID > $MY_MARKER
wait $MY_RUNID
CODE=$?
echo $$ > $MY_MARKER
cd $MY_LANDINGZONE
echo "==========================="
echo "Job exit code: $CODE"
echo "==========================="
updatejobinfo $CODE

# Copy files to the SE
if [ $CODE -eq 0 -a -n "$SE_OUTPUT_FILES" ]; then
	se_copy "file://$MY_SCRATCH" "$SE_PATH" "$SE_OUTPUT_FILES"
fi

# Move output into landingzone
my_move "$MY_SCRATCH" "$MY_LANDINGZONE" "$SB_OUTPUT_FILES"

checkdir "Start directory" "$MY_LANDINGZONE"
checkdir "Scratch directory" "$MY_SCRATCH"

cleanup
trap - 0 1 2 3 15
echo "Job finished"

exit $CODE

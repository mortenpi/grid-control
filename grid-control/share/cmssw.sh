#!/bin/bash

echo "CMSSW module starting"
echo "---------------------"

source _config.sh

_find() {
	if test -f "$MY_SCRATCH/$1"; then
		echo "$MY_SCRATCH/$1"
	elif test -f "$MY_REAL/$1"; then
		echo "$MY_REAL/$1"
	else
		echo "$1 not found" 2>&1
		exit 1
	fi
}

processConfig() {
	sed -e "s@__FILE_NAMES__@$FNAMES@" \
	    -e "s@__MAX_EVENTS__@$EVENTS@" \
	    -e "s@__SKIP_EVENTS__@$SKIP@" \
	    -e "s@__MY_JOB__@$MY_JOB@" \
	    $SEED_REPLACER \
	    < "`_find $1`"
}

if ! [ -n "$VO_CMS_SW_DIR" ]; then
	echo VO_CMS_SW_DIR undefined 2>&1
	exit 1
fi

if [ ! -f "$VO_CMS_SW_DIR/cmsset_default.sh" ]; then
	echo "$VO_CMS_SW_DIR/cmsset_default.sh" not found 2>&1
	exit 1
fi

saved_SCRAM_VERSION="$SCRAM_VERSION"
saved_SCRAM_ARCH="$SCRAM_ARCH"
source "$VO_CMS_SW_DIR/cmsset_default.sh"
SCRAM_VERSION="$saved_SCRAM_VERSION"
export SCRAM_ARCH="$saved_SCRAM_ARCH"

SCRAM="`which \"\$SCRAM_VERSION\"`"
if [ -z "$SCRAM" ]; then
	echo "$SCRAM_VERSION not found" 2>&1
	exit 1
fi

if ! $SCRAM project CMSSW $SCRAM_PROJECTVERSION; then
	echo "SCRAM project area setup failed" 2>&1
	exit 1
fi

if ! test -d "$SCRAM_PROJECTVERSION"; then
	echo "SCRAM project area not found" 2>&1
	exit 1
fi

cd "$SCRAM_PROJECTVERSION"
if ! [ "$HAS_RUNTIME" = no ]; then
	tar xvfz "`_find runtime.tar.gz`"
fi

echo "---------------------------"

EVENTS="$1"
SKIP="$2"
FNAMES="\"$3\""
shift 3
for i in "$@"; do
	FNAMES="$FNAMES, \"$i\""
done

SEED_REPLACER=""
j=0
for i in $SEEDS; do
	eval SEED_$j=$[i+MY_JOB]
	SEED_REPLACER="$SEED_REPLACER -e s@__SEED_${j}__@$[i+MY_JOB]@"
	j=$[j+1]
done

for i in $CMSSW_CONFIG; do
	echo "*** $i:"
	processConfig "$i"
done

echo "---------------------------"

eval `$SCRAM runtime -sh`

mkdir -p workdir &> /dev/null
cd workdir

export CMSSW_SEARCH_PATH="$CMSSW_SEARCH_PATH:`pwd`"

eval "for i in $USER_INFILES; do mv \"\$MY_SCRATCH/\$i\" .; done"
echo "which cmsRun:"
which cmsRun
echo "ls before CMSSW:"
ls -la

echo "---------------------------"

for i in $CMSSW_CONFIG; do
	processConfig "$i" > "$i"

	if [ "$GZIP_OUT" = "yes" ]; then
		( cmsRun "$i"; echo $? > exitcode.txt ) 2>&1 | gzip -9 > cmssw_out.txt.gz
		CODE=$(<exitcode.txt)
		rm -f exitcode.txt
        else 
		cmsRun "$i"
		CODE=$?
	fi
done

echo "---------------------------"
echo "ls after CMSRUN:"
ls -la

eval "for i in $MY_OUT $SE_OUTPUT_FILES; do mv \"\$i\" \"\$MY_SCRATCH\" &> /dev/null; done"

exit $CODE

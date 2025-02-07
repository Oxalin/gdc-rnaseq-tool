import requests
import json
import urllib
import pandas as pd
import sys
import hashlib
import argparse
import os, fnmatch, gzip, shutil, tarfile
import re
from pathlib import Path
import time

## -------------- JSON Filters constructor :
class Filter(object):

    def __init__(self):
        self.filter = {"op": "and","content": []}

    def add_filter(self, Field, Value, Operator):
        self.filter['content'].append({"op":Operator,"content":{"field":Field,"value":Value}})

    def create_filter(self):
        self.final_filter = json.dumps(self.filter,separators=(',',':'))

## -------------- Function for downloading files :
def download(uuid, name, md5, ES, WF, DT, retry=0):
    try :
        def md5_ok() :
            with open(fout, 'rb') as f :
                return (md5 == hashlib.md5(f.read()).hexdigest())

        fout = OFILE['data'].format(ES=ES, WF=WF, DT=DT, uuid=uuid, name=name)

#        print("Checking if file already exists")
        if Path(fout).exists():
#            print(fout + " already exists. Comparing MD5.")
            if md5_ok():
#                print("MD5 Sum OK. Skipping.")
                return (uuid, retry, md5_ok())
            else:
                os.remove(fout)
                print("MD5 Sum mismatch. Old " + uuid + " removed.")

        print("Downloading (attempt {}): {}".format(retry, uuid))
        url = PARAM['url-data'].format(uuid=uuid)

        with urllib.request.urlopen(url) as response :
            data = response.read()

        os.makedirs(os.path.dirname(fout), exist_ok=True)

        with open(fout, 'wb') as f :
            f.write(data)

        if md5_ok():    # Check if file downloaded correctly
            return (uuid, retry, md5_ok())
        else:
            os.remove(fout)
            raise ValueError('MD5 Sum Error on ' + uuid)
    except Exception as e :
        print("Error (attempt {}): {}".format(retry, e))
        if (retry >= PARAM['max retry']) :
            raise e
        return download(uuid, name, md5, ES, WF, DT, retry + 1)

## -------------- Function to check if valid manifest file
def validate_manifest(manifest_loc):
    with open(manifest_loc,'r') as myfile:
        if myfile.readline()[0:2] != 'id': # Check header at first line
            print('Bad Manifest File: ' + manifest_loc + ". Skipping.")
        else:
            return True

## -------------- Function for reading manifest file :
def read_manifest(manifest_loc):
    uuid_list = []
    if validate_manifest(manifest_loc):
        with open(manifest_loc,'r') as myfile:
            myfile.readline() # Read header at first line
            for x in myfile:
                uuid = x.split('\t')[0]
                uuid_list.append(uuid)
    return uuid_list

## -------------- Function that unpacks gz files into another directory :
def gunzip(file_path,output_path):
    with gzip.open(file_path,"rb") as f_in, open(output_path,"wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

## -------------- Argument Parser Function :
def arg_parse():
    parser = argparse.ArgumentParser(
        description='----GDC RNA Seq File Merging Tool v0.2----',
        usage= 'python3 gdc-rnaseq-tool.py [options] MANIFEST_PATH')
    parser.add_argument('manifest_path', action="store", help='Path to manifest file or directory')
##    parser.add_argument('-u', action='store_true', help='Search for UUIDs (not implemented)')
    parser.add_argument('-g','--hugo', action="store_true", help='Add Hugo Symbol Name')
    parser.add_argument('-r','--recursive', action="store_true", help='Recursive search of manifest files (TXT and CSV) in a directory')

    parser.add_argument(
        '-o', '--output', type=Path, default="Merged_RNASeq-"+ time.strftime("%Y%m%d-%H%M%S"),
        metavar='PATH',
        help="Output folder to download data (default: Merged_RNASeq-{timestamp})"
    )

    args = parser.parse_args()
    return args


## -------------- Errors when passing incorrect name :
def error_parse(code):
    '''
    Generates the error messages
    '''
    error = {
        "bad_mani":"Input must be valid GDC Manifest. " \
        "\n\tGo to https://portal.gdc.cancer.gov/ to download a manifest",
    }
    print("ERROR: " + error[code])
    sys.exit(2)

## -------------- Main function :
def main(args):
    global manifest_path
    global hugo
    global recursive_search
    global output_path
    manifest_path = args.manifest_path
    hugo = args.hugo
    recursive_search = args.recursive
    output_path = args.output

# 0. Run Program
# -------------------------------------------------------
main(arg_parse())

# If recursive search, list all manifest files
manifest_list = []

if recursive_search == True:
    regex = re.compile('(.*txt$)|(.*csv$)')

    for root, dirs, files in os.walk(manifest_path):
        for file in files:
            if regex.match(file):
                FilePath = os.path.join(root, file)
                if validate_manifest(FilePath):
                    print(FilePath)
                    manifest_list.append(FilePath)
else:
    manifest_list.append(manifest_path)

for manifest_file in manifest_list:
    # Get current time
    timestr = time.strftime("%Y%m%d-%H%M%S")

    # 1. Read in manifest and set output folder
    # -------------------------------------------------------
    Manifest_Loc = manifest_file
#    Manifest_Loc = str(Manifest_Loc.replace('\\', '').strip())
#    print(Manifest_Loc)
#    Output_Dir = str(Path(File).parents[0]) + '/Merged_RNASeq_' + timestr + '/' # Create path object from the directory
    Output_Dir = str(output_path) + "/"

    print('Reading Manifest File from: ' + Manifest_Loc)
    print('Downloading Files to: ' + Output_Dir)

    UUIDs = read_manifest(Manifest_Loc)

    # 2. Get info about files in manifest
    # -------------------------------------------------------
    File_Filter = Filter()
    File_Filter.add_filter("file_id",UUIDs,"in")
    ## Pourquoi limitait-t-il les workflow types à une sélection? Pour leurs besoins spécifiques? Il n'y a pas de raisons apparentes, trouvons tout
    ## et ce sera classé par Experimental Strategy / Workflow Type en fonction des fichiers ID dans le manifest
    RNASeq_WFs = ["HTSeq - Counts","HTSeq - FPKM","HTSeq - FPKM-UQ","STAR - Counts"]
    miRNAs_WFs = ["BCGSC miRNA Profiling"]
    workflow_types = RNASeq_WFs + miRNAs_WFs
    print(workflow_types)
    File_Filter.add_filter("analysis.workflow_type",workflow_types,"in")
    File_Filter.create_filter()

    EndPoint = "files"
    Fields = "cases.samples.portions.analytes.aliquots.submitter_id,file_name,cases.samples.sample_type,file_id,md5sum,experimental_strategy,analysis.workflow_type,data_type"
    Size = "10000"

    Payload = {
        "filters":File_Filter.final_filter,
        "format":"json",
        "fields":Fields,
        "size":Size
    }

    print("Getting info about listed files from the manifest")
    r = requests.post('https://api.gdc.cancer.gov/' + EndPoint, json=Payload)
#    print(r.text)
    data = json.loads(r.text)
    file_list = data['data']['hits']

    if len(file_list) == 0:
        sys.exit("Request to apigdc.cancer.gov returned no results. Exiting...")

    Dictionary = {}
    TCGA_Barcode_Dict = {}
    for file in file_list:
        UUID = file['file_id']
        Barcode = file['cases'][0]['samples'][0]['portions'][0]['analytes'][0]['aliquots'][0]['submitter_id']
#        File_Name = os.path.splitext(file['file_name'])[0]
        File_Name = file['file_name']

        Dictionary[UUID] = {'File Name': File_Name,
        'TCGA Barcode':Barcode,
        'MD5': file['md5sum'],
        'Sample Type': file['cases'][0]['samples'][0]['sample_type'],
        'Experimental Strategy': file['experimental_strategy'],
        'Workflow Type': file['analysis']['workflow_type'],
        'Data Type': file['data_type']}

#        TCGA_Barcode_Dict[File_Name] = {Barcode}
        TCGA_Barcode_Dict[os.path.splitext(File_Name)[0]] = {Barcode}
#        print("TCGA_Barcode_Dict[Filename]: " + File_Name)

    # 3. Download files
    # -------------------------------------------------------

    # Location to save files as they are downloaded
    os.makedirs(Output_Dir, exist_ok=True)
    OFILE = {'data':Output_Dir+"{ES}/{WF}/{DT}/{uuid}/{name}"}

    PARAM = {
        # URL
        'url-data' : "https://api.gdc.cancer.gov/data/{uuid}",

        # Persistence upon error
        'max retry' : 10,
    }

    print("Downloading files")
    for key, value in Dictionary.items():
        download(key,
                value['File Name'],
                value['MD5'],
                value['Experimental Strategy'],
                value['Workflow Type'],
                value['Data Type'])

    # 4. Merge the RNA Seq files
    # -------------------------------------------------------

    GZipLocs = [Output_Dir + 'RNA-Seq/' + WF for WF in RNASeq_WFs]

    # Add Hugo Symbol
    if hugo == True:
        url = 'https://github.com/cpreid2/gdc-rnaseq-tool/raw/master/Gene_Annotation/gencode.v22.genes.txt'
        gene_map = pd.read_csv(url,sep='\t')
        gene_map = gene_map[['gene_id','gene_name']]
        gene_map = gene_map.set_index('gene_id')

    print("Merging the RNA Seq files")
    for i in range(len(RNASeq_WFs)):

        # Peut-il y avoir des fichiers .gz qui soient téléchargés?
        # Peut-il y avoir des fichiers de formats / extensions autres?
        # Find all .gz files and ungzip into the folder
        gzip_pattern = '*.gz'
        tsv_pattern = '*.tsv'
        TSV_Files = []

#        # Create .gz directory in subfolder
#        if os.path.exists(GZipLocs[i] + '/UnzippedFiles/'):
#            shutil.rmtree(GZipLocs[i] + '/UnzippedFiles/')
#        os.makedirs(GZipLocs[i] + '/UnzippedFiles/')

        for root, dirs, files in os.walk(GZipLocs[i]):
            for filename in fnmatch.filter(files, gzip_pattern):
                OldFilePath = os.path.join(root, filename)
#                NewFilePath = os.path.join(GZipLocs[i] + '/UnzippedFiles/', filename.replace(".gz",".tsv"))
                NewFilePath = os.path.join(root, filename.replace(".gz",".tsv"))

                gunzip(OldFilePath, NewFilePath) # unzip to New file path
                print("Adding " + NewFilePath)
                TSV_Files.append(NewFilePath) # append tsv file to list of files

            for filename in fnmatch.filter(files, tsv_pattern): # append tsv file to list of files
                print ("Adding " + os.path.join(root, filename))
                TSV_Files.append(os.path.join(root, filename))

        Matrix = {}

        for file in TSV_Files:
            p = Path(file)
            Name = str(p.name).replace('.tsv','')
#            Name = Name + '.gz'
            Name = TCGA_Barcode_Dict[Name]
            Name = str(list(Name)[0])
            print(file)
            print("Name is " + Name)
            Counts_DataFrame = pd.read_csv(file,sep='\t',header=None,names=['GeneId', Name])
            Matrix[Name] = tuple(Counts_DataFrame[Name])

        # Merge Matrices to dataframes and write to files
        if len(Matrix) > 0:
            Merged_File_Name = 'Merged_'+ RNASeq_WFs[i].replace('HTSeq - ','') + '.tsv'
            print('Creating merged ' + RNASeq_WFs[i] + ' File... ' + '( ' + Merged_File_Name + ' )')
            Counts_Final_Df = pd.DataFrame(Matrix, index=tuple((Counts_DataFrame['GeneId'])))
            if hugo == True:
                Counts_Final_Df = gene_map.merge(Counts_Final_Df, how='outer', left_index=True, right_index=True)
            Counts_Final_Df.to_csv(str(Output_Dir) + '/' + Merged_File_Name,sep='\t',index=True)

    # 5. Merge the miRNA Seq files
    # -------------------------------------------------------
    miRNASeq_WF = ['BCGSC miRNA Profiling']
    miRNASeq_DTs = ['Isoform Expression Quantification','miRNA Expression Quantification']
    miRNALocs = [Output_Dir + 'miRNA-Seq/BCGSC miRNA Profiling/' + DT for DT in miRNASeq_DTs]

    print("Merging the miRNA Seq file")

    for i in range(len(miRNASeq_DTs)):

        # Find all .gz files and ungzip into the folder
        pattern = '*.mirnas.quantification.txt'
        Files = []

        for root, dirs, files in os.walk(miRNALocs[i]):
            for filename in fnmatch.filter(files, pattern):
                FilePath = os.path.join(root, filename)

                Files.append(FilePath) # append file to list of files

        miRNA_count_Matrix = {}
        miRNA_rpmm_Matrix = {}

        for file in Files:
            p = Path(file)
            Name = str(p.name)
            Name = TCGA_Barcode_Dict[Name]
            Name = str(list(Name)[0])

            miRNA_DataFrame = pd.read_csv(file,sep='\t')

            miRNA_count_DataFrame = miRNA_DataFrame[['miRNA_ID','read_count']]
            miRNA_count_DataFrame.columns = ['miRNA_ID',Name]

            miRNA_rpmm_DataFrame = miRNA_DataFrame[['miRNA_ID','reads_per_million_miRNA_mapped']]
            miRNA_rpmm_DataFrame.columns = ['miRNA_ID',Name]

            miRNA_count_Matrix[Name] = tuple(miRNA_count_DataFrame[Name])
            miRNA_rpmm_Matrix[Name] = tuple(miRNA_rpmm_DataFrame[Name])

        if len(miRNA_count_Matrix) > 0:
            print('Creating merged miRNASeq Counts File... ( Merged_miRNA_Counts.tsv )')
            miRNA_Count_Final_Df = pd.DataFrame(miRNA_count_Matrix, index=tuple((miRNA_count_DataFrame['miRNA_ID'])))
            miRNA_Count_Final_Df.to_csv(str(Output_Dir) + '/Merged_miRNA_Counts.tsv',sep='\t',index=True)
        if len(miRNA_rpmm_Matrix) > 0:
            print('Creating merged miRNASeq rpmm File... ( Merged_miRNA_rpmm.tsv )')
            miRNA_rpmm_Final_Df = pd.DataFrame(miRNA_rpmm_Matrix, index=tuple((miRNA_rpmm_DataFrame['miRNA_ID'])))
            miRNA_rpmm_Final_Df.to_csv(str(Output_Dir) + '/Merged_miRNA_rpmm.tsv',sep='\t',index=True)

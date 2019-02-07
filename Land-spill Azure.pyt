#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
# vim:ft=python
# vim:ff=unix
#
# Copyright © 2019 Pi-Yueh Chuang <pychuang@gwu.edu>
#
# Distributed under terms of the MIT license.

"""
ArcGIS Pro Python toolbox.
"""
import os
import numpy
import helpers.arcgistools
import helpers.azuretools
import importlib
importlib.reload(helpers.arcgistools)


class Toolbox(object):
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "Land-spill Azure"
        self.alias = "landspill"

        # List of tool classes associated with this toolbox
        self.tools = [PrepareGeoClawCases, CreateAzureCredentialFile,
                      RunCasesOnAzure]

class PrepareGeoClawCases(object):
    """Prepare case folders, configurations, and input files for GeoClaw."""

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "CreateGeoClawCases"
        self.description = \
            "Prepare case folders, configurations, and input files for GeoClaw."

        self.canRunInBackground = False # no effect in ArcGIS Pro

    def getParameterInfo(self):
        """Define parameter definitions"""

        params = []

        # =====================================================================
        # Basic section
        # =====================================================================

        # 0, basic: working directory
        working_dir = arcpy.Parameter(
            category="Basic", displayName="Working Directory", name="working_dir",
            datatype="DEWorkspace", parameterType="Required", direction="Input")

        working_dir.value = arcpy.env.scratchFolder

        # 1, basic: rupture point
        rupture_point = arcpy.Parameter(
            category="Basic", displayName="Rupture point", name="rupture_point",
            datatype="GPFeatureLayer", parameterType="Required", direction="Input")

        rupture_point.filter.list = ["Point"]

        # 2, basic: leak profile
        leak_profile = arcpy.Parameter(
            category="Basic", displayName="Leak profile", name="leak_profile",
            datatype="GPValueTable", parameterType="Required", direction="Input")

        leak_profile.columns = [
            ["GPDouble", "End time (sec)"], ["GPDouble", "Rate (m^3/sec)"]]
        leak_profile.value = [[1800.0, 0.5], [12600.0, 0.1]]

        # 3, basic: base topography
        topo_layer = arcpy.Parameter(
            category="Basic", displayName="Base topography", name="topo_layer",
            datatype="GPRasterLayer", parameterType="Required", direction="Input")

        # 4, basic: hydrological features
        hydro_layers = arcpy.Parameter(
            category="Basic", displayName="Hydrological features",
            name="hydro_layers", datatype="GPFeatureLayer",
            parameterType="Optional", direction="Input", multiValue=True)

        # 5, 6, basic: finest resolution
        x_res = arcpy.Parameter(
            category="Basic", displayName="X resolution (m)", name="x_res",
            datatype="GPDouble", parameterType="Required", direction="Input")

        y_res = arcpy.Parameter(
            category="Basic", displayName="Y resolution (m)", name="y_res",
            datatype="GPDouble", parameterType="Required", direction="Input")

        # 7, 8, 9, 10, basic: computational extent relative to point source
        dist_top = arcpy.Parameter(
            category="Basic",
            displayName="Relative computational doamin: top (m)",
            name="dist_top",
            datatype="GPDouble", parameterType="Required", direction="Input")

        dist_bottom = arcpy.Parameter(
            category="Basic",
            displayName="Relative computational doamin: bottom (m)",
            name="dist_bottom",
            datatype="GPDouble", parameterType="Required", direction="Input")

        dist_left = arcpy.Parameter(
            category="Basic",
            displayName="Relative computational doamin: left (m)",
            name="dist_left",
            datatype="GPDouble", parameterType="Required", direction="Input")

        dist_right = arcpy.Parameter(
            category="Basic",
            displayName="Relative computational doamin: right (m)",
            name="dist_right",
            datatype="GPDouble", parameterType="Required", direction="Input")

        dist_top.value = dist_bottom.value = dist_left.value = dist_right.value = 1000

        params += [working_dir, rupture_point, leak_profile, topo_layer, hydro_layers,
                   x_res, y_res, dist_top, dist_bottom, dist_left, dist_right]

        # =====================================================================
        # Fluid settings section
        # =====================================================================

        # 11
        ref_viscosity = arcpy.Parameter(
            category="Fluid settings",
            displayName="Reference dynamic viscosity (cP)", name="ref_viscosity",
            datatype="GPDouble", parameterType="Required", direction="Input")
        ref_viscosity.value = 332.0

        # 12
        ref_temp = arcpy.Parameter(
            category="Fluid settings",
            displayName="Reference temperature (Celsius)", name="ref_temp",
            datatype="GPDouble", parameterType="Required", direction="Input")
        ref_temp.value = 15.0

        # 13
        temp = arcpy.Parameter(
            category="Fluid settings",
            displayName="Ambient temperature (Celsius)", name="temp",
            datatype="GPDouble", parameterType="Required", direction="Input")
        temp.value= 25.0

        # 14
        density = arcpy.Parameter(
            category="Fluid settings",
            displayName="Density (kg/m^3)", name="density",
            datatype="GPDouble", parameterType="Required", direction="Input")
        density.value= 9.266e2

        # 15
        evap_type = arcpy.Parameter(
            category="Fluid settings",
            displayName="Evaporation model", name="evap_type",
            datatype="GPString", parameterType="Required", direction="Input")
        evap_type.filter.type = "ValueList"
        evap_type.filter.list = ["None", "Fingas1996 Log Law", "Fingas1996 SQRT Law"]
        evap_type.value = "Fingas1996 Log Law"

        # 16
        evap_c1 = arcpy.Parameter(
            category="Fluid settings",
            displayName="Evaporation coefficients 1", name="evap_c1",
            datatype="GPDouble", parameterType="Optional", direction="Input")
        evap_c1.value = 1.38

        # 17
        evap_c2 = arcpy.Parameter(
            category="Fluid settings",
            displayName="Evaporation coefficients 2", name="evap_c2",
            datatype="GPDouble", parameterType="Optional", direction="Input")
        evap_c2.value = 0.045


        params += [ref_viscosity, ref_temp, temp, density, evap_type, evap_c1, evap_c2]

        # =====================================================================
        # Darcy-Weisbach section
        # =====================================================================

        # 18
        friction_type = arcpy.Parameter(
            category="Darcy-Weisbach friction settings",
            displayName="Darcy-Weisbach model", name="friction_type",
            datatype="GPString", parameterType="Required", direction="Input")
        friction_type.filter.type = "ValueList"
        friction_type.filter.list = ["None", "Three-regime model"]
        friction_type.value = "Three-regime model"

        # 19
        roughness =  arcpy.Parameter(
            category="Darcy-Weisbach friction settings",
            displayName="Surface roughness", name="roughness",
            datatype="GPDouble", parameterType="Optional", direction="Input")
        roughness.value = 0.1

        params += [friction_type, roughness]

        # =====================================================================
        # Misc
        # =====================================================================

        ignore = arcpy.Parameter(
            category="Misc",
            displayName="Skip setup if a case folder already exists",
            name="ignore",
            datatype="GPBoolean", parameterType="Required", direction="Input")
        ignore.value = True

        params += [ignore]

        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""

        # update the default cell x size based on provided base topo
        if parameters[3].altered and not parameters[5].altered:
            parameters[5].value = arcpy.Describe(
                parameters[3].valueAsText).meanCellWidth

        # update the default cell y size based on x size
        if parameters[5].altered and not parameters[6].altered:
            parameters[6].value = parameters[5].value

        if parameters[15].value == "None":
            parameters[16].enabled = False
            parameters[17].enabled = False

        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        importlib.reload(helpers.arcgistools)
        arcpy.env.parallelProcessingFactor="75%"

        # path of the working directory
        working_dir = parameters[0].valueAsText.replace("\\", "\\\\")

        # xy coordinates of rupture locations (Npoints x 2)
        points = arcpy.da.FeatureClassToNumPyArray(
            parameters[1].valueAsText, ["SHAPE@X", "SHAPE@Y"],
            spatial_reference=arcpy.SpatialReference(3857))

        # profile of leak rate (Nstages x 2)
        leak_profile = numpy.array(parameters[2].value, dtype=numpy.float64)

        # base topography file
        base_topo = parameters[3].valueAsText

        # hydrological feature layers (1D array with size Nfeatures)
        if parameters[4].value is None:
            hydro_layers = []
        else:
            hydro_layers = [
                parameters[4].value.getRow(i).strip("' ")
                for i in range(parameters[4].value.rowCount)]

        # finest resolution in x & y direction
        resolution = numpy.array(
            [parameters[5].value, parameters[6].value], dtype=numpy.float64)

        # computational domain extent (relative to rupture points)
        domain = numpy.array(
            [parameters[7].value, parameters[8].value,
             parameters[9].value, parameters[10].value], dtype=numpy.float64)

        # fluid properties
        ref_mu=parameters[11].value
        ref_temp=parameters[12].value
        amb_temp=parameters[13].value
        density=parameters[14].value
        evap_type=parameters[15].value
        evap_coeffs=numpy.array([parameters[16].value, parameters[17].value])

        # friction
        friction_type = parameters[18].value
        roughness = parameters[19].value

        # misc
        ignore = parameters[-1].value

        # initialize an Azure mission
        # mission = helpers.azuretools.Mission(
        #     credential, "landspill-azure", max_nodes, [], vm_type)

        # loop through each point to create each case and submit to Azure
        for i, point in enumerate(points):

            # create case folder
            arcpy.AddMessage("Creating case folder for point {}".format(point))
            case_path = helpers.arcgistools.create_single_folder(
                working_dir, point, ignore)

            # create topography ASCII file
            arcpy.AddMessage("Creating topo input for point {}".format(point))
            topo = helpers.arcgistools.prepare_single_topo(
                base_topo, point, domain, case_path, ignore)

            # create ASCII rasters for hydorlogical files
            arcpy.AddMessage("Creating hydro input for point {}".format(point))
            hydros = helpers.arcgistools.prepare_single_point_hydros(
                hydro_layers, point, domain, min(resolution), case_path, ignore)

            # create setrun.py and roughness
            arcpy.AddMessage("Creating GeoClaw config for point {}".format(point))
            setrun, roughness_file = helpers.arcgistools.write_setrun(
                out_dir=case_path, point=point, extent=domain, res=resolution,
                ref_mu=ref_mu, ref_temp=ref_temp, amb_temp=amb_temp,
                density=density, leak_profile=leak_profile,
                evap_type=evap_type, evap_coeffs=evap_coeffs,
                n_hydros = len(hydros),
                friction_type=friction_type, roughness=roughness)

            arcpy.AddMessage("Done preparing point {}".format(point))

        return

class CreateAzureCredentialFile(object):
    """Create an encrpyted Azure credential file."""

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "NewEncrpytedAzureCredential"
        self.description = "Create an encrpyted Azure credential file."
        self.canRunInBackground = False # no effect in ArcGIS Pro

    def getParameterInfo(self):
        """Define parameter definitions"""

        # 0, working directory
        working_dir = arcpy.Parameter(
            displayName="Working Directory", name="working_dir",
            datatype="DEWorkspace", parameterType="Required", direction="Input")

        working_dir.value = arcpy.env.scratchFolder

        # 1, output file name
        output_file = arcpy.Parameter(
            displayName="Output credential file name", name="output_file",
            datatype="GPString", parameterType="Required", direction="Input")

        output_file.value = "azure_cred.bin"

        # 2: Batch account name
        azure_batch_name = arcpy.Parameter(
            displayName="Azure Batch account name", name="azure_batch_name",
            datatype="GPStringHidden", parameterType="Required", direction="Input")

        # 3: Batch account key
        azure_batch_key = arcpy.Parameter(
            displayName="Azure Batch account key", name="azure_batch_key",
            datatype="GPStringHidden", parameterType="Required", direction="Input")

        # 4: Batch account URL
        azure_batch_URL = arcpy.Parameter(
            displayName="Azure Batch account URL", name="azure_batch_URL",
            datatype="GPStringHidden", parameterType="Required", direction="Input")

        # 5: Storage account name
        azure_storage_name = arcpy.Parameter(
            displayName="Azure Storage account name", name="azure_storage_name",
            datatype="GPStringHidden", parameterType="Required", direction="Input")

        # 6: Storage account key
        azure_storage_key = arcpy.Parameter(
            displayName="Azure Storage account key", name="azure_storage_key",
            datatype="GPStringHidden", parameterType="Required", direction="Input")

        # 7: Encryption passcode
        passcode = arcpy.Parameter(
            displayName="Passcode", name="passcode",
            datatype="GPStringHidden", parameterType="Required", direction="Input")

        # 8: Encryption passcode confirm
        confirm_passcode = arcpy.Parameter(
            displayName="Confirm passcode", name="confirm_passcode",
            datatype="GPStringHidden", parameterType="Required", direction="Input")

        params = [working_dir, output_file,
                  azure_batch_name, azure_batch_key, azure_batch_URL,
                  azure_storage_name, azure_storage_key,
                  passcode, confirm_passcode]

        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""

        if parameters[7].value != parameters[8].value:
            parameters[8].setErrorMessage("Passcode does not match.")

        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # path of the working directory
        working_dir = parameters[0].valueAsText.replace("\\", "\\\\")

        # output file name
        output = parameters[1].value

        # azure credential
        credential = helpers.azuretools.UserCredential(
            parameters[2].value, parameters[3].value, parameters[4].value,
            parameters[5].value, parameters[6].value)

        # passcode
        passcode = parameters[7].value

        # write the file
        credential.write_encrypted(passcode, os.path.join(working_dir, output))

        return

class RunCasesOnAzure(object):
    """Submit and run cases on Azure."""

    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "RunCasesOnAzure"
        self.description =  "Submit and run cases on Azure."
        self.canRunInBackground = False # no effect in ArcGIS Pro

    def getParameterInfo(self):
        """Define parameter definitions"""

        params = []

        # 0, basic: working directory
        working_dir = arcpy.Parameter(
            displayName="Working Directory", name="working_dir",
            datatype="DEWorkspace", parameterType="Required", direction="Input")

        working_dir.value = arcpy.env.scratchFolder

        # 1, basic: rupture point
        rupture_point = arcpy.Parameter(
            displayName="Rupture point", name="rupture_point",
            datatype="GPFeatureLayer", parameterType="Required", direction="Input")

        rupture_point.filter.list = ["Point"]

        # 2: maximum number of computing nodes
        max_nodes = arcpy.Parameter(
            displayName="Maximum number of computing nodes", name="max_nodes",
            datatype="GPLong", parameterType="Required", direction="Input")

        max_nodes.value = 2

        # 3: vm type
        vm_type = arcpy.Parameter(
            displayName="Computing node type", name="vm_type",
            datatype="GPString", parameterType="Required", direction="Input")

        vm_type.filter.type = "ValueList"
        vm_type.filter.list = ["STANDARD_A1_V2", "STANDARD_H8", "STANDARD_H16"]
        vm_type.value = "STANDARD_H8"

        # 4: credential type
        cred_type = arcpy.Parameter(
            displayName="Azure credential", name="cred_type",
            datatype="GPString", parameterType="Required", direction="Input")

        cred_type.filter.type = "ValueList"
        cred_type.filter.list = ["Encrypted file", "Manual input"]
        cred_type.value = "Encrypted file"

        # 5: encrypted credential file
        cred_file = arcpy.Parameter(
            displayName="Encrypted credential file", name="cred_file",
            datatype="DEFile", parameterType="Optional", direction="Input",
            enabled=True)

        cred_file.value = os.path.join(arcpy.env.scratchFolder, "azure_cred.bin")

        # 6: passcode
        passcode = arcpy.Parameter(
            displayName="Passcode for the credential file", name="passcode",
            datatype="GPStringHidden", parameterType="Optional",
            direction="Input", enabled=True)

        # 7: Batch account name
        azure_batch_name = arcpy.Parameter(
            displayName="Azure Batch account name", name="azure_batch_name",
            datatype="GPStringHidden", parameterType="Optional",
            direction="Input", enabled=False)

        # 8: Batch account key
        azure_batch_key = arcpy.Parameter(
            displayName="Azure Batch account key", name="azure_batch_key",
            datatype="GPStringHidden", parameterType="Optional",
            direction="Input", enabled=False)

        # 9: Batch account URL
        azure_batch_URL = arcpy.Parameter(
            displayName="Azure Batch account URL", name="azure_batch_URL",
            datatype="GPStringHidden", parameterType="Optional",
            direction="Input", enabled=False)

        # 10: Storage account name
        azure_storage_name = arcpy.Parameter(
            displayName="Azure Storage account name", name="azure_storage_name",
            datatype="GPStringHidden", parameterType="Optional",
            direction="Input", enabled=False)

        # 11: Storage account key
        azure_storage_key = arcpy.Parameter(
            displayName="Azure Storage account key", name="azure_storage_key",
            datatype="GPStringHidden", parameterType="Optional",
            direction="Input", enabled=False)

        params += [working_dir, rupture_point, max_nodes, vm_type,
                   cred_type, cred_file, passcode,
                   azure_batch_name, azure_batch_key, azure_batch_URL,
                   azure_storage_name, azure_storage_key]

        # =====================================================================
        # Misc
        # =====================================================================

        # 12: Skip a case if its case folder doesn't exist locally
        ignore_local_nonexist = arcpy.Parameter(
            displayName="Skip submitting/running a case if its case folder " + \
                        "doesn't exist on local machine",
            name="ignore_local_nonexist",
            datatype="GPBoolean", parameterType="Required", direction="Input")
        ignore_local_nonexist.value = False

        # 13: Skip a case if its case folder already exist on Azure
        ignore_azure_exist = arcpy.Parameter(
            displayName="Do not re-submit a case if it already " + \
                        "exists on Azure",
            name="ignore_azure_exist",
            datatype="GPBoolean", parameterType="Required", direction="Input")
        ignore_azure_exist.value = True

        params += [ignore_local_nonexist, ignore_azure_exist]

        return params

    def isLicensed(self):
        """Set whether tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""

        parameters[5].enabled = (parameters[4].value == "Encrypted file")
        parameters[6].enabled = (parameters[4].value == "Encrypted file")
        for i in range(7, 12):
            parameters[i].enabled = (not parameters[5].enabled)

        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter.  This method is called after internal validation."""

        if parameters[4].value == "Encrypted file":
            if parameters[5].value is None:
                parameters[5].setErrorMessage("Require a credential file.")

            if parameters[6].value is None:
                parameters[6].setErrorMessage("Require passcode.")
        else:
            for i in range(7, 12):
                if parameters[i].value is None:
                    parameters[i].setErrorMessage("Cannot be empty.")
        return

    def execute(self, parameters, messages):
        """The source code of the tool."""

        # path of the working directory
        working_dir = parameters[0].valueAsText.replace("\\", "\\\\")

        # xy coordinates of rupture locations (Npoints x 2)
        points = arcpy.da.FeatureClassToNumPyArray(
            parameters[1].valueAsText, ["SHAPE@X", "SHAPE@Y"],
            spatial_reference=arcpy.SpatialReference(3857))

        # azure credential
        max_nodes = parameters[2].value
        vm_type = parameters[3].value

        # skip a case if its case folder doesn't exist locally
        ignore_local_nonexist = parameters[12].value

        # skip a case if its case folder already exist on Azure
        ignore_azure_exist = parameters[13].value

        # Azure credential
        if parameters[4].value == "Encrypted file":
            credential = helpers.azuretools.UserCredential()
            credential.read_encrypted(
                parameters[6].valueAsText, parameters[5].valueAsText)
        else:
            credential = helpers.azuretools.UserCredential(
                parameters[7].value, parameters[8].value, parameters[9].value,
                parameters[10].value, parameters[11].value)

        # initialize an Azure mission
        mission = helpers.azuretools.Mission(
            credential, "landspill-azure", max_nodes, [],
            output=os.devnull, vm_type=vm_type)

        # start mission (creating pool, storage, scheduler)
        mission.start(ignore_local_nonexist, ignore_azure_exist)

        # loop through each point to add case to Azure task scheduler
        for i, point in enumerate(points):

            x = "{}{}".format(numpy.abs(point[0]), "E" if point[0]>=0 else "W")
            y = "{}{}".format(numpy.abs(point[1]), "N" if point[1]>=0 else "S")
            x = x.replace(".", "_")
            y = y.replace(".", "_")
            case = os.path.join(working_dir, "{}{}".format(x, y))

            arcpy.AddMessage("Adding case {}".format(case))
            result = mission.add_task(case, ignore_local_nonexist, ignore_azure_exist)
            arcpy.AddMessage(result)

            if i == (max_nodes - 1):
                mission.force_resize(max_nodes)

        if points.shape[0] < max_nodes:
            mission.force_resize(points.shape[0])

        return

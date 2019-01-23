#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2019 Pi-Yueh Chuang <pychuang@gwu.edu>
#
# Distributed under terms of the MIT license.

"""
A controller for the mission (i.e., object that can issue action on Azure).
"""
import os
import sys
import time
import datetime
import logging
import pickle
import azure.batch.models
import azure.storage.blob
import azure.common
from helpers import UserCredential
from helpers import MissionInfo


class MissionController():
    """MissionController"""

    def __init__(self, user_credential, mission_info, output=sys.stdout):
        """__init__

        Args:
            user_credential [in]: An instance of UserCredential.
            mission_info [in]: A MissionInfo object.
            output [in]: a string for output file or an opened file object.
        """

        assert isinstance(user_credential, UserCredential), "Type error!"
        assert isinstance(mission_info, MissionInfo), "Type error!"

        # Azure credential
        self.credential = user_credential

        # an alias/pointer to the MissionInfo object
        self.info = mission_info

        # output file
        if isinstance(output, str):
            self.output = open(output, "a")
            self.close_output = True
        else:
            self.close_output = False

        # Batch service client
        self.batch_client = self.credential.create_batch_client()

        # Storage service client
        self.storage_client = self.credential.create_blob_client()

        # we use one container for one mission, and we initialize the info here
        self.container_token = None
        self.container_url = None

        # variable to track what we uploaded
        self.uploaded_dirs = {}

    def __del__(self):
        """__del__

        Destructor.
        """

        if self.close_output:
            self.output.close()

    def _create_pool(self):
        """Create a pool on Azure based on the mission info."""

        # if the pool already exists (it does not mean it's ready)
        if self.batch_client.pool.exists(pool_id=self.info.pool_name):
            logging.info("Pool %s already exists.", self.info.pool_name)

            # get the number of nodes in the pool on Azure
            pool_info = self.batch_client.pool.get(self.info.pool_name)

            # check if the size of the pool matches the self
            if pool_info.target_dedicated_nodes != self.info.n_nodes:
                logging.info(
                    "Pool %s does not have the required number of nodes. \
                     Issuing a resizing command.",
                    self.info.pool_name)

                # an alias for shorter code
                pool_resizing = azure.batch.models.AllocationState.resizing
                pool_steady = azure.batch.models.AllocationState.steady

                # if the pool is under resizing, stop the resizing first
                if pool_info.allocation_state is pool_resizing:
                    self.batch_client.pool.stop_resize(self.info.pool_name)

                    while pool_info.allocation_state is not pool_steady:
                        time.sleep(2) # wait for 2 seconds
                        # get updated information of the pool
                        pool_info = self.batch_client.pool.get(self.info.pool_name)

                # now resizing
                self.batch_client.pool.resize(
                    pool_id=self.info.pool_name,
                    pool_resize_parameter=azure.batch.models.PoolResizeParameter(
                        target_dedicated_nodes=self.info.n_nodes,
                        node_deallocation_option="requeue"))

                logging.info("Resizing command issued.")

        # if the batch client is not aware of this pool
        else:
            logging.info("Issuing creation to pool %s.", self.info.pool_name)

            # image
            image = azure.batch.models.ImageReference(
                publisher="microsoft-azure-batch",
                offer="ubuntu-server-container",
                sku="16-04-lts",
                version="latest")

            # prefetched Docker image
            container_conf = azure.batch.models.ContainerConfiguration(
                container_image_names=['barbagroup/landspill:applications'])

            # vm setting
            vm_conf = azure.batch.models.VirtualMachineConfiguration(
                image_reference=image,
                container_configuration=container_conf,
                node_agent_sku_id="batch.node.ubuntu 16.04")

            # pool setting
            pool_conf = azure.batch.models.PoolAddParameter(
                id=self.info.pool_name,
                virtual_machine_configuration=vm_conf,
                vm_size=self.info.vm_type,
                target_dedicated_nodes=self.info.n_nodes)

            # create the pool
            self.batch_client.pool.add(pool_conf)

            logging.info("Creation command issued.")

    def _delete_pool(self):
        """Delete a pool on Azure based on the content set in self."""

        logging.info("Issuing deletion to pool %s.", self.info.pool_name)

        # if the pool exists, issue a delete command
        if self.batch_client.pool.exists(pool_id=self.info.pool_name):
            self.batch_client.pool.delete(self.info.pool_name)
            logging.info("Deletion command issued.")
        else:
            logging.info(
                "Pool %s does not exist. Skip deletion.", self.info.pool_name)

    def _create_storage_container(self):
        """Create a blob container for this mission."""

        # create a container
        logging.info("Creating container %s", self.info.container_name)
        try:
            created = self.storage_client.create_container(
                container_name=self.info.container_name, fail_on_exist=True)
        except azure.common.AzureConflictHttpError as err:
            if err.error_code == "ContainerAlreadyExists":
                logging.info(
                    "The container %s already exists. SKIP creation.",
                    self.info.container_name)

                if self.storage_client.exists(
                        container_name=self.info.container_name,
                        blob_name="uploaded_dirs.dat"):

                    logging.info("Downloading uploaded_dirs.dat to recover info.")
                    self.storage_client.get_blob_to_path(
                        container_name=self.info.container_name,
                        blob_name="uploaded_dirs.dat", file_path="uploaded_dirs.dat")
                    logging.info("Done downloading uploaded_dirs.dat.")

                    with open("uploaded_dirs.dat", "rb") as f:
                        self.uploaded_dirs = pickle.loads(f.read())
                    logging.info("uploaded_dirs recovered.")
                    os.remove("uploaded_dirs.dat")

            elif err.error_code == "ContainerBeingDeleted":
                created = False
                counter = 0
                while not created:
                    logging.warning(
                        "The container %s is undergoing deletion. \
                         Retry in 5 secs.",
                        self.info.container_name)

                    time.sleep(5)

                    created = self.storage_client.create_container(
                        container_name=self.info.container_name,
                        fail_on_exist=False)

                    counter += 1
                    if counter > 120:
                        logging.error(
                            "Retry timeout. Re-creating the container failed.")
                        raise RuntimeError(
                            "The container %s has been undergoing deletion for "
                            "over 600 seconds. Please manually check the status.")
            else:
                raise

        logging.info("Container %s created/exists.", self.info.container_name)

        # use current time as the sharing start time
        current_utc_time = \
            datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

        # get the SAS token
        self.container_token = \
            self.storage_client.generate_container_shared_access_signature(
                container_name=self.info.container_name,
                permission=azure.storage.blob.ContainerPermissions(
                    True, True, True, True),
                start=current_utc_time,
                expiry=current_utc_time+datetime.timedelta(days=1))
        logging.info("SAS token for %s obtained.", self.info.container_name)

        # get the SAS url
        self.container_url = \
            self.storage_client.make_container_url(
                container_name=self.info.container_name,
                sas_token=self.container_token)

        # not sure why there's an extra key in the url. Need to remove it.
        self.container_url = \
            self.container_url.replace("restype=container&", "")
        logging.info("SAS URL for %s obtained.", self.info.container_name)

    def _delete_storage_container(self):
        """delete_all_data"""

        logging.info(
            "Issuing deletion to container %s.", self.info.container_name)

        self.storage_client.delete_container(
            container_name=self.info.container_name, fail_not_exist=True)

        logging.info("Deletion issued.")

    def _create_job(self):
        """Create a job (i.e. task scheduler) for this mission."""

        # job parameters
        job_params = azure.batch.models.JobAddParameter(
            id=self.info.job_name,
            pool_info=azure.batch.models.PoolInformation(
                pool_id=self.info.pool_name))

        logging.info("Issuing creation to job %s", self.info.job_name)

        # add job
        try:
            self.batch_client.job.add(job_params)
            logging.info("Creation command issued.")
        except azure.batch.models.BatchErrorException as err:
            if err.message.value.startswith("The specified job already exists."):
                logging.info("Job already exists. SKIP creation.")
            else:
                raise

    def _delete_job(self):
        """Delete the mission job (i.e. task scheduler)."""

        logging.info("Issuing deletion to job %s", self.info.job_name)

        self.batch_client.job.delete(self.info.job_name)

        logging.info("Deletion command issued.")

    def _upload_dir(self, dir_path):
        """Upload a directory to the mission container."""

        # get the full and absolute path (and basename)
        dir_path = os.path.abspath(os.path.normpath(dir_path))
        dir_base_name = os.path.basename(dir_path)

        # check if the base name conflicts any uploaded cases
        if dir_base_name in self.uploaded_dirs.keys():
            logging.error(
                "A case with the same base name %s already exists in the \
                 container. Can't upload it.", dir_base_name)
            raise RuntimeError(
                "A case with the same base name {} ".format(dir_base_name) +
                "already exists in the container. Can't upload it.")

        # check if the container was created
        assert self.container_url is not None
        assert self.container_token is not None

        logging.info("Uploading directory %s.", dir_path)

        # upload files
        for dirpath, dirs, files in os.walk(dir_path):
            for f in files:
                file_path = os.path.join(os.path.abspath(dirpath), f)
                blob_name = os.path.relpath(file_path, os.path.dirname(dir_path))

                logging.info("Uploading file %s.", file_path)
                self.storage_client.create_blob_from_path(
                    container_name=self.info.container_name, blob_name=blob_name,
                    file_path=file_path, max_connections=4)
                logging.info("Done uploading file %s.", file_path)

        logging.info("Done uploading directory %s.", dir_path)

        # add the case name and the parent path to the tracking list
        self.uploaded_dirs[dir_base_name] = os.path.dirname(dir_path)

        # write the uploaded info to a file and upload to the container as a log
        with open("uploaded_dirs.dat", "wb") as f:
            f.write(pickle.dumps(self.uploaded_dirs))

        logging.info("Uploading uploaded_dirs.dat")
        self.storage_client.create_blob_from_path(
            container_name=self.info.container_name, blob_name="uploaded_dirs.dat",
            file_path="uploaded_dirs.dat", max_connections=2)
        logging.info("Done uploading uploaded_dirs.dat")

        os.remove("uploaded_dirs.dat")

    def _download_dir(self, dir_path, ignore_not_exist=True):
        """Download a directory from the mission blob container."""

        # get the full and absolute path
        dir_path = os.path.abspath(os.path.normpath(dir_path))
        dir_base_name = os.path.basename(dir_path)

        # check if the container exists
        assert self.container_url is not None
        assert self.container_token is not None

        logging.info("Downloading directory %s.", dir_path)

        if dir_base_name not in self.uploaded_dirs.keys():
            if not ignore_not_exist:
                logging.error(
                    "Directory %s is not in the container.", dir_path)
                raise RuntimeError(
                    "Directory {} is not in the container.".format(dir_path))
            else:
                logging.warning(
                    "Directory %s is not in the container. SKIP.", dir_path)
        else:
            blob_list = self.storage_client.list_blobs(
                container_name=self.info.container_name,
                prefix="{}/".format(dir_base_name), num_results=50000)

            for blob in blob_list:
                file_abs_path = os.path.join(
                    self.uploaded_dirs[dir_base_name], blob.name)

                if not os.path.isdir(os.path.dirname(file_abs_path)):
                    os.makedirs(os.path.dirname(file_abs_path))

                logging.info("Downloading file %s.", file_abs_path)
                self.storage_client.get_blob_to_path(
                    container_name=self.info.container_name,
                    blob_name=blob.name, file_path=file_abs_path)
                logging.info("Done downloading file %s.", file_abs_path)

            logging.info("Done downloading directory %s.", dir_path)

    def _delete_dir(self, dir_path, ignore_not_exist=True):
        """Delete a directory from the mission's container."""

        # get the full and absolute path
        dir_path = os.path.abspath(os.path.normpath(dir_path))
        dir_base_name = os.path.basename(dir_path)

        # check if the container exists
        assert self.container_url is not None
        assert self.container_token is not None

        logging.info("Deleting %s from container.", dir_base_name)

        if dir_base_name not in self.uploaded_dirs.keys():
            if not ignore_not_exist:
                logging.error(
                    "Directory %s is not in the container.", dir_path)
                raise RuntimeError(
                    "Directory {} is not in the container.".format(dir_path))
            else:
                logging.warning(
                    "Directory %s is not in the container. SKIP.", dir_path)
        else:
            blob_list = self.storage_client.list_blobs(
                container_name=self.info.container_name,
                prefix="{}/".format(dir_base_name), num_results=50000)

            for blob in blob_list:
                logging.info("Deleting file %s.", blob.name)
                self.storage_client.delete_blob(
                    container_name=self.info.container_name,
                    blob_name=blob.name)
                logging.info("Done deleting file %s.", blob.name)

            logging.info("Done downloading directory %s.", dir_path)

            logging.info("Updating uploaded_dirs.dat")
            del self.uploaded_dirs[dir_base_name]
            with open("uploaded_dirs.dat", "wb") as f:
                f.write(pickle.dumps(self.uploaded_dirs))

            logging.info("Uploading uploaded_dirs.dat")
            self.storage_client.create_blob_from_path(
                container_name=self.info.container_name, blob_name="uploaded_dirs.dat",
                file_path="uploaded_dirs.dat", max_connections=2)
            logging.info("Done uploading uploaded_dirs.dat")

            os.remove("uploaded_dirs.dat")

    def add_task(self, case):
        """Add a task to the mission's job (i.e., task scheduler).

        Args:
            case [in]: str; the name of case directory
        """

        # upload to the storage container
        self._upload_dir(case)

        # get the full and absolute path
        case_path = os.path.abspath(os.path.normpath(case))
        case = os.path.basename(case_path)

        task_container_settings = azure.batch.models.TaskContainerSettings(
            image_name="barbagroup/landspill:applications",
            container_run_options="--rm " + \
                "--workdir /home/landspill/geoclaw-landspill-cases")

        input_data = [
            azure.batch.models.ResourceFile(
                storage_container_url=self.container_url,
                blob_prefix="{}/".format(case))]

        output_data = [
            azure.batch.models.OutputFile(
                file_pattern="{}/**/*".format(case),
                upload_options=azure.batch.models.OutputFileUploadOptions(
                    upload_condition= \
                    azure.batch.models.OutputFileUploadCondition.task_completion),
                destination=azure.batch.models.OutputFileDestination(
                    container= \
                    azure.batch.models.OutputFileBlobContainerDestination(
                        container_url=self.container_url,
                        path="{}".format(case))))]

        command = "/bin/bash -c \"" + \
            "cp -r $AZ_BATCH_TASK_WORKING_DIR/{} ./ && ".format(case) + \
            "python run.py {} && ".format(case) + \
            "python createnc.py {} && ".format(case) + \
            "python plotdepths.py --border {} && ".format(case) + \
            "cp -r ./{} $AZ_BATCH_TASK_WORKING_DIR".format(case) + \
            "\""

        task_params = azure.batch.models.TaskAddParameter(
            id=case,
            command_line=command,
            container_settings=task_container_settings,
            resource_files=input_data,
            output_files=output_data)

        logging.info("Add task %s.", case)
        self.batch_client.task.add(self.info.job_name, task_params)
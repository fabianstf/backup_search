#Backup Exec Script to start, check and restore

param(
    $jobname
    ,$restorefolder
    ,$modulepath = "C:\Program Files\Veritas\Backup Exec\Modules\PowerShell3\BEMCLI"
    ,$option
    ,$smtp
    ,$to
    ,$from
    ,$user
    ,$password
    ,$port
    ,$subject = "Veritas backup log for "+ (Get-Date -Format "MM/dd/yy")
    ,$body = "See attached log file for details."
    ,$report
    ,$reportpath
	,$arrService
)

if(test-path $modulepath)
{ import-module $modulepath }
else
{
    Write-Host "Can't find PS module!"
    Exit 100
}

#Checking for mandatory parameters
if($option -eq "")
{
    Write-Host "-option Must be specified! Options are: Full, Incremental, Differencial or Restore."
    Exit 200
}

if($to -eq "" -or $password -eq "")
{
    Write-Host "-to and -password Must be specified! It must contain the recipeits email address (Global Properties can be used) and the password for the email account."
    Exit 200
}

#Main Logic
if($option -eq "full" -or $option -eq "incremental" -or $option -eq "differential")
{
	if($jobname -eq "")
	{
    	Write-Host "-jobname Must be specified! Check the job name in Veritas (Global Properties can be used)."
    	Exit 200
	}

    #Part 1: Start job: Full backup (Parameter: Job Name)
    $job = Get-BEJob -Name $jobname
    $job | Start-BEJob -Confirm:$false

    #Wait for job to finish
    $job | Wait-BEJob

    #Part 2: Get Job Log (create XML and send email...?)
    $body = $job | Get-BEJobHistory -FromLastJobRun | Get-BeJobLog -OutputStyle Html

    #Send email with log
    $secpasswd = ConvertTo-SecureString "$password" -AsPlainText -Force
    $mycreds = New-Object System.Management.Automation.PSCredential ($user, $secpasswd) 

    Send-MailMessage -SmtpServer $smtp -To $to -From $from -Subject $subject -Body $body -BodyAsHtml -UseSSL -Credential $mycreds -Port $port

    $status = (Get-BEJob -Name $jobname).Status 
    if($status -ne "Succeeded")
    {
        Write-Host "Backup: $jobname `r`nStatus:$status!"
        Exit 101
    }
}
elseif($option -eq "restore")
{
    #Checking if restorefolder parameter is not null
    
    if($restorefolder -eq "")
    {
        Write-Host "For the Restore job, the -restorefolder Must be specified! It must contain the folder where the files will be restored (Global Properties can be used)."
        Exit 200
    }
	if($jobname -eq "")
	{
    	Write-Host "-jobname Must be specified! Check the job name in Veritas (Global Properties can be used)."
    	Exit 200
	}
    
    #Part 1: Restore (Parameters: Job Name and Folder)
    $job = Get-BEJob -Name $jobname 
    $restorejob = $job | Get-BEJobHistory -FromLastJobRun | Submit-BEFileSystemRestoreJob -FileSystemSelection $restorefolder

    #Wait for job to finish
    $restorejob | Wait-BEJob

    #Part 2: Get Job Log (create XML and send email...?)
    $body = $restorejob | Get-BEJobHistory -FromLastJobRun | Get-BeJobLog -OutputStyle Html

    #Send email with log
    $secpasswd = ConvertTo-SecureString "$password" -AsPlainText -Force
    $mycreds = New-Object System.Management.Automation.PSCredential ($user, $secpasswd) 

    Send-MailMessage -SmtpServer $smtp -To $to -From $from -Subject $subject -Body $body -BodyAsHtml -UseSSL -Credential $mycreds -Port $port

    $status = (Get-BEJob -Name $restorejob.Name).Status 
    $restorejobName = $restorejob.Name
    if($status -ne "Succeeded")
    {
        Write-Host "$restorejobName `r`nStatus:$status!"
        Exit 101
    }
}
elseif($option -eq "report")
{
    if($report -eq "")
    {
        Write-Host "For the Report job, the -report Must be specified! It must contain the report name."
        Exit 200
    }

    if($reportpath -eq "")
    {
        Write-Host "For the Report job, the -reportpath Must be specified! It must contain the path to wehre the report will be placed after execution."
        Exit 200
    }

    Get-BEReport "$report" | Invoke-BEReport -Path "$reportpath\$report.html"
    $body = Get-Content -Path "$reportpath\$report.html" -raw

    $secpasswd = ConvertTo-SecureString "$password" -AsPlainText -Force
    $mycreds = New-Object System.Management.Automation.PSCredential ($user, $secpasswd) 
        
    Send-MailMessage -SmtpServer $smtp -To $to -From $from -Subject $subject -Body $body -BodyAsHtml -UseSSL -Credential $mycreds -Port $port
}
elseif($option -eq "cleanup")
{
    $deleted = @((Get-BEJob "*" | Get-BEJobHistory | Remove-BEJobHistory -PassThru -Confirm:$false).JobName)
    
    if($deleted)
    { Write-Host "Job History deleted: `r`n$deleted" }
    else
    { Write-Host "No job history found" }
}

elseif($option -eq "service")
{
	Write-Host "`r`n********* STATUS OF THE BACKUP EXEC SERVICES *********"
       $arrService = Get-Service -Name "bedbg"
	if ($arrService.Status -ne "Running")
		{
		Write-Host "`r`nBackup Exec Service " $arrService " IS NOT running!"
		Exit 300
		}
	if ($arrService.Status -eq "running")
	{ 
	Write-Host "`r`nBackup Exec Service " $arrService " is running!"
	}

	$arrService = Get-Service -Name "BackupExecAgentAccelerator"
	if ($arrService.Status -ne "Running")
		{
		Write-Host "`r`nBackup Exec Service " $arrService " IS NOT running!"
		Exit 300
		}
	if ($arrService.Status -eq "running")
	{ 
	Write-Host "`r`nBackup Exec Service " $arrService " is running!"
	}

	$arrService = Get-Service -Name "BackupExecDeviceMediaService"
	if ($arrService.Status -ne "Running")
		{
		Write-Host "`r`nBackup Exec Service " $arrService " IS NOT running!"
		Exit 300
		}
	if ($arrService.Status -eq "running")
	{ 
	Write-Host "`r`nBackup Exec Service " $arrService " is running!"
	}

	$arrService = Get-Service -Name "BackupExecRPCService"
	if ($arrService.Status -ne "Running")
		{
		Write-Host "`r`nBackup Exec Service " $arrService " IS NOT running!"
		Exit 300
		}
	if ($arrService.Status -eq "running")
	{ 
	Write-Host "`r`nBackup Exec Service " $arrService " is running!"
	}

	$arrService = Get-Service -Name "BackupExecAgentBrowser"
	if ($arrService.Status -ne "Running")
		{
		Write-Host "`r`nBackup Exec Service " $arrService " IS NOT running!"
		Exit 300
		}
	if ($arrService.Status -eq "running")
	{ 
	Write-Host "`r`nBackup Exec Service " $arrService " is running!"
	}

	$arrService = Get-Service -Name "BackupExecManagementService"
	if ($arrService.Status -ne "Running")
		{
		Write-Host "`r`nBackup Exec Service " $arrService " IS NOT running!"
		Exit 300
		}
	if ($arrService.Status -eq "running")
	{ 
	Write-Host "`r`nBackup Exec Service " $arrService " is running!"
	}

	$arrService = Get-Service -Name "BackupExecJobEngine"
	if ($arrService.Status -ne "Running")
		{
		Write-Host "`r`nBackup Exec Service " $arrService " IS NOT running!"
		Exit 300
		}
	if ($arrService.Status -eq "running")
	{ 
	Write-Host "`r`nBackup Exec Service " $arrService " is running!"
	}
}
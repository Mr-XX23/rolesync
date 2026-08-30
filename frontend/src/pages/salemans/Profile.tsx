import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useAppDispatch, useAppSelector } from '../../store';
import { 
  fetchProfile, 
  updateProfile, 
  uploadAvatar,
  uploadAvatarUrl,
  fetchWorkspaces, 
  updateWorkspaceDetails
} from '../../store/workspaceSlice';
import { useToast } from '../../context/ToastContext';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { 
  User, 
  Bot, 
  Building2, 
  Link2, 
  Mail, 
  MapPin, 
  Camera, 
  GraduationCap, 
  Plus, 
  X, 
  Award, 
  Heart, 
  Layers, 
  ShieldCheck, 
  Save, 
  Loader2,
  Globe,
  Phone
} from 'lucide-react';

const AVATAR_PRESETS = [
  'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=400&auto=format&fit=crop&q=80',
  'https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=400&auto=format&fit=crop&q=80',
];

const LinkedinIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.28 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.75M6.46 10.9v8.37H9.2V10.9H6.46M7.83 6.25c-.91 0-1.64.73-1.64 1.64s.73 1.64 1.64 1.64 1.64-.73 1.64-1.64-.73-1.64-1.64-1.64Z"/>
  </svg>
);

const GithubIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
  </svg>
);

const FacebookIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/>
  </svg>
);

const XIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
  </svg>
);

const InstagramIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="currentColor" viewBox="0 0 24 24">
    <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/>
  </svg>
);

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_REGEX = /^[+]?[(]?[0-9]{1,4}[)]?[-\s./0-9]{6,20}$/;
const URL_REGEX = /^https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_+.~#?&/=]*)$/;

const sanitizeInputString = (val: string | undefined | null): string => {
  if (!val) return '';
  return val
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/<[^>]+>/g, '')
    .replace(/javascript:/gi, '')
    .replace(/data:/gi, '');
};

export const Profile: React.FC = () => {
  const dispatch = useAppDispatch();
  const toast = useToast();
  const { profile, isLoading, workspaces, currentWorkspace } = useAppSelector((state) => state.workspace);
  const { user } = useAppSelector((state) => state.auth);

  const [activeTab, setActiveTab] = useState<'bio' | 'ai-context' | 'workspace' | 'connected'>('bio');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Avatar upload states
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Form states - Empty by default (no dummy data)
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [customImageUrl, setCustomImageUrl] = useState('');
  const [jobTitle, setJobTitle] = useState('');
  const [department, setDepartment] = useState('');
  const [organization, setOrganization] = useState('');
  const [location, setLocation] = useState('');
  const [secondaryEmail, setSecondaryEmail] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [bio, setBio] = useState('');

  // Education & Expertise
  const [education, setEducation] = useState('');
  const [expertiseTags, setExpertiseTags] = useState<string[]>([]);
  const [newExpertiseTag, setNewExpertiseTag] = useState('');
  const [skillsTags, setSkillsTags] = useState<string[]>([]);
  const [newSkillTag, setNewSkillTag] = useState('');

  // Interests & Hobbies
  const [interestsTags, setInterestsTags] = useState<string[]>([]);
  const [newInterestTag, setNewInterestTag] = useState('');
  const [hobbiesTags, setHobbiesTags] = useState<string[]>([]);
  const [newHobbyTag, setNewHobbyTag] = useState('');

  // AI Persona & Working Style
  const [aiPersonaContext, setAiPersonaContext] = useState('');
  const [communicationStyle, setCommunicationStyle] = useState('Strategic & Concise');
  const [autonomyLevel, setAutonomyLevel] = useState('Supervised Execution');

  // Social & External Links
  const [linkedinUrl, setLinkedinUrl] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [websiteUrl, setWebsiteUrl] = useState('');
  const [facebookUrl, setFacebookUrl] = useState('');
  const [xUrl, setXUrl] = useState('');
  const [instagramUrl, setInstagramUrl] = useState('');

  // Workspace Settings
  const [workspaceName, setWorkspaceName] = useState('');
  const [workspaceDescription, setWorkspaceDescription] = useState('');
  const [isUpdatingWorkspace, setIsUpdatingWorkspace] = useState(false);

  // Initial load
  useEffect(() => {
    dispatch(fetchProfile());
    dispatch(fetchWorkspaces());
  }, [dispatch]);

  // Sync state from loaded profile without any fake/dummy data
  useEffect(() => {
    if (profile) {
      setFirstName(profile.firstName || '');
      setLastName(profile.lastName || '');
      setDisplayName(profile.displayName || (profile.firstName ? `${profile.firstName} ${profile.lastName || ''}`.trim() : ''));
      setAvatarUrl(profile.avatarUrl || '');
      setJobTitle(profile.jobTitle || '');
      setDepartment(profile.department || '');
      setOrganization(profile.organization || '');
      setLocation(profile.location || '');
      setSecondaryEmail(profile.secondaryEmail || '');
      setPhoneNumber(profile.phoneNumber || '');
      setBio(profile.bio || '');
      setEducation(profile.education || '');

      setExpertiseTags(
        profile.expertise 
          ? profile.expertise.split(',').map((s: string) => s.trim()).filter(Boolean) 
          : []
      );

      setSkillsTags(
        profile.skills 
          ? profile.skills.split(',').map((s: string) => s.trim()).filter(Boolean) 
          : []
      );

      setInterestsTags(
        profile.interests 
          ? profile.interests.split(',').map((s: string) => s.trim()).filter(Boolean) 
          : []
      );

      setHobbiesTags(
        profile.hobbies 
          ? profile.hobbies.split(',').map((s: string) => s.trim()).filter(Boolean) 
          : []
      );

      setAiPersonaContext(profile.aiPersonaContext || '');
      setCommunicationStyle(profile.communicationStyle || 'Strategic & Concise');
      setLinkedinUrl(profile.linkedinUrl || '');
      setGithubUrl(profile.githubUrl || '');
      setWebsiteUrl(profile.websiteUrl || '');
      setFacebookUrl(profile.facebookUrl || '');
      setXUrl(profile.xUrl || '');
      setInstagramUrl(profile.instagramUrl || '');
    }
  }, [profile]);

  useEffect(() => {
    if (currentWorkspace) {
      setWorkspaceName(currentWorkspace.name || '');
      setWorkspaceDescription(currentWorkspace.description || '');
    } else if (workspaces.length > 0) {
      setWorkspaceName(workspaces[0].name || '');
      setWorkspaceDescription(workspaces[0].description || '');
    }
  }, [currentWorkspace, workspaces]);

  // Dirty state checks for each tab (Enables Save button only when modified)
  const isBioTabDirty = useMemo(() => {
    if (!profile) return false;
    const initialDisplay = profile.displayName || (profile.firstName ? `${profile.firstName} ${profile.lastName || ''}`.trim() : '');
    return (
      (firstName || '').trim() !== (profile.firstName || '').trim() ||
      (lastName || '').trim() !== (profile.lastName || '').trim() ||
      (displayName || '').trim() !== initialDisplay.trim() ||
      (avatarUrl || '').trim() !== (profile.avatarUrl || '').trim() ||
      (jobTitle || '').trim() !== (profile.jobTitle || '').trim() ||
      (department || '').trim() !== (profile.department || '').trim() ||
      (organization || '').trim() !== (profile.organization || '').trim() ||
      (location || '').trim() !== (profile.location || '').trim() ||
      (secondaryEmail || '').trim() !== (profile.secondaryEmail || '').trim() ||
      (phoneNumber || '').trim() !== (profile.phoneNumber || '').trim() ||
      (bio || '').trim() !== (profile.bio || '').trim() ||
      (education || '').trim() !== (profile.education || '').trim()
    );
  }, [profile, firstName, lastName, displayName, avatarUrl, jobTitle, department, organization, location, secondaryEmail, phoneNumber, bio, education]);

  const isAiContextTabDirty = useMemo(() => {
    if (!profile) return false;
    const savedExp = profile.expertise ? profile.expertise.split(',').map((s: string) => s.trim()).filter(Boolean) : [];
    const savedSkills = profile.skills ? profile.skills.split(',').map((s: string) => s.trim()).filter(Boolean) : [];
    const savedInterests = profile.interests ? profile.interests.split(',').map((s: string) => s.trim()).filter(Boolean) : [];
    const savedHobbies = profile.hobbies ? profile.hobbies.split(',').map((s: string) => s.trim()).filter(Boolean) : [];

    const arraysEqual = (a: string[], b: string[]) => 
      a.length === b.length && a.every((val, idx) => val === b[idx]);

    return (
      (aiPersonaContext || '').trim() !== (profile.aiPersonaContext || '').trim() ||
      (communicationStyle || 'Strategic & Concise') !== (profile.communicationStyle || 'Strategic & Concise') ||
      !arraysEqual(expertiseTags, savedExp) ||
      !arraysEqual(skillsTags, savedSkills) ||
      !arraysEqual(interestsTags, savedInterests) ||
      !arraysEqual(hobbiesTags, savedHobbies)
    );
  }, [profile, aiPersonaContext, communicationStyle, expertiseTags, skillsTags, interestsTags, hobbiesTags]);

  const isWorkspaceTabDirty = useMemo(() => {
    const currentWs = currentWorkspace || workspaces[0];
    if (!currentWs) return false;
    return (
      (workspaceName || '').trim() !== (currentWs.name || '').trim() ||
      (workspaceDescription || '').trim() !== (currentWs.description || '').trim()
    );
  }, [currentWorkspace, workspaces, workspaceName, workspaceDescription]);

  const isConnectedTabDirty = useMemo(() => {
    if (!profile) return false;
    return (
      (linkedinUrl || '').trim() !== (profile.linkedinUrl || '').trim() ||
      (githubUrl || '').trim() !== (profile.githubUrl || '').trim() ||
      (facebookUrl || '').trim() !== (profile.facebookUrl || '').trim() ||
      (xUrl || '').trim() !== (profile.xUrl || '').trim() ||
      (instagramUrl || '').trim() !== (profile.instagramUrl || '').trim() ||
      (websiteUrl || '').trim() !== (profile.websiteUrl || '').trim()
    );
  }, [profile, linkedinUrl, githubUrl, facebookUrl, xUrl, instagramUrl, websiteUrl]);

  // Phone input sanitization handler - allows digits and international format characters
  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawVal = e.target.value;
    if (/^[0-9+\-().\s]*$/.test(rawVal) || rawVal === '') {
      setPhoneNumber(rawVal);
      if (fieldErrors.phoneNumber) {
        setFieldErrors(prev => {
          const updated = { ...prev };
          delete updated.phoneNumber;
          return updated;
        });
      }
    }
  };

  // Handle Tag additions/removals with security and duplicate validation
  const addTag = (
    value: string, 
    list: string[], 
    setList: React.Dispatch<React.SetStateAction<string[]>>, 
    setValue: React.Dispatch<React.SetStateAction<string>>
  ) => {
    const cleanTag = sanitizeInputString(value).trim();
    if (!cleanTag) return;

    if (cleanTag.length > 50) {
      toast.warning('Individual tags must not exceed 50 characters.', 'Tag Limit');
      return;
    }

    if (list.length >= 25) {
      toast.warning('Maximum of 25 tags allowed per category.', 'Tag Limit');
      return;
    }

    const isDuplicate = list.some(t => t.toLowerCase() === cleanTag.toLowerCase());
    if (!isDuplicate) {
      setList([...list, cleanTag]);
    }
    setValue('');
  };

  const removeTag = (
    indexToRemove: number, 
    list: string[], 
    setList: React.Dispatch<React.SetStateAction<string[]>>
  ) => {
    setList(list.filter((_, idx) => idx !== indexToRemove));
  };

  // Direct Cloudinary file upload
  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const allowedTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/jpg'];
    if (!allowedTypes.includes(file.type.toLowerCase())) {
      toast.error('Invalid image format. Please select a JPEG, PNG, WebP, or GIF image.', 'Invalid Format');
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    const MAX_SIZE = 5 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      toast.error('File size exceeds the 5MB maximum limit. Please choose a smaller image.', 'File Too Large');
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    setIsUploadingAvatar(true);
    try {
      const resultAction = await dispatch(uploadAvatar(file));
      if (uploadAvatar.fulfilled.match(resultAction)) {
        const hostedUrl = resultAction.payload.avatar_url;
        setAvatarUrl(hostedUrl);
        setCustomImageUrl(''); // Keep bottom direct URL input clean/empty on manual file upload
        toast.success('Profile photo uploaded and saved successfully.', 'Photo Uploaded');
        if (fieldErrors.avatarUrl) {
          setFieldErrors(prev => {
            const updated = { ...prev };
            delete updated.avatarUrl;
            return updated;
          });
        }
      } else {
        const msg = (resultAction.payload as string) || 'Failed to upload profile photo. Please try again.';
        toast.error(msg, 'Upload Failed');
      }
    } catch (err: any) {
      const msg = err.message || 'An unexpected error occurred during image upload.';
      toast.error(msg, 'Upload Failed');
    } finally {
      setIsUploadingAvatar(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Host external URL (Preset or direct URL) permanently
  const handleHostRemoteImageUrl = async (urlToHost: string, isFromTextInput = false) => {
    const cleanUrl = urlToHost.trim();
    if (!cleanUrl) return;

    if (!cleanUrl.startsWith('http://') && !cleanUrl.startsWith('https://')) {
      toast.error('Image URL must start with http:// or https://', 'Invalid URL');
      return;
    }

    if (!isFromTextInput) {
      setCustomImageUrl(''); // Clear text box if selecting preset avatar
    }

    // If already hosted in our storage, simply set it
    if (cleanUrl.includes('cloudinary.com') && cleanUrl.includes('rolesync')) {
      setAvatarUrl(cleanUrl);
      return;
    }

    setIsUploadingAvatar(true);
    try {
      const resultAction = await dispatch(uploadAvatarUrl(cleanUrl));
      if (uploadAvatarUrl.fulfilled.match(resultAction)) {
        const permanentUrl = resultAction.payload.avatar_url;
        setAvatarUrl(permanentUrl);
        toast.success('Profile avatar updated successfully.', 'Avatar Updated');
        if (fieldErrors.avatarUrl) {
          setFieldErrors(prev => {
            const updated = { ...prev };
            delete updated.avatarUrl;
            return updated;
          });
        }
      } else {
        // Graceful fallback: Still set the URL so preset/direct link displays and can be saved
        setAvatarUrl(cleanUrl);
        toast.info('Using direct image link for profile.', 'Avatar Set');
      }
    } catch (err: any) {
      setAvatarUrl(cleanUrl);
      toast.info('Using direct image link for profile.', 'Avatar Set');
    } finally {
      setIsUploadingAvatar(false);
    }
  };

  // Calculate readiness metric dynamically based on completed fields
  const calculateAiReadiness = (): number => {
    let score = 0;
    if (firstName.trim()) score += 10;
    if (lastName.trim()) score += 10;
    if (jobTitle.trim()) score += 10;
    if (department.trim()) score += 10;
    if (avatarUrl.trim()) score += 10;
    if (bio.trim().length > 30) score += 15;
    if (aiPersonaContext.trim().length > 50) score += 20;
    if (expertiseTags.length > 0) score += 5;
    if (skillsTags.length > 0) score += 5;
    if (linkedinUrl.trim() || githubUrl.trim() || websiteUrl.trim() || facebookUrl.trim() || xUrl.trim() || instagramUrl.trim()) score += 5;
    return Math.min(score, 100);
  };

  // Client-side form validation for Tab 1 (Bio-Data)
  const validateBioTab = (): boolean => {
    const errors: Record<string, string> = {};

    if (!firstName.trim()) {
      errors.firstName = 'First name is required.';
    } else if (firstName.trim().length < 2 || firstName.trim().length > 50) {
      errors.firstName = 'First name must be between 2 and 50 characters.';
    }

    if (!lastName.trim()) {
      errors.lastName = 'Last name is required.';
    } else if (lastName.trim().length < 2 || lastName.trim().length > 50) {
      errors.lastName = 'Last name must be between 2 and 50 characters.';
    }

    if (displayName.trim() && displayName.trim().length > 100) {
      errors.displayName = 'Display name must not exceed 100 characters.';
    }

    if (secondaryEmail.trim()) {
      if (!EMAIL_REGEX.test(secondaryEmail.trim()) || secondaryEmail.trim().length > 100) {
        errors.secondaryEmail = 'Please enter a valid secondary email address.';
      }
    }

    if (phoneNumber.trim()) {
      if (!PHONE_REGEX.test(phoneNumber.trim()) || phoneNumber.trim().length > 25) {
        errors.phoneNumber = 'Please enter a valid phone number (e.g. +1 555 123 4567).';
      }
    }

    if (avatarUrl.trim()) {
      if (!URL_REGEX.test(avatarUrl.trim()) || avatarUrl.trim().length > 1000) {
        errors.avatarUrl = 'Avatar URL must be a valid HTTPS URL (max 1000 chars).';
      }
    }

    if (bio.trim() && bio.trim().length > 3000) {
      errors.bio = 'Bio must not exceed 3000 characters.';
    }

    if (education.trim() && education.trim().length > 3000) {
      errors.education = 'Education details must not exceed 3000 characters.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // Client-side form validation for Tab 2 (AI Context)
  const validateAiContextTab = (): boolean => {
    const errors: Record<string, string> = {};

    if (aiPersonaContext.trim() && aiPersonaContext.trim().length > 5000) {
      errors.aiPersonaContext = 'AI persona instructions must not exceed 5000 characters.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // Client-side form validation for Tab 3 (Workspace)
  const validateWorkspaceTab = (): boolean => {
    const errors: Record<string, string> = {};

    if (!workspaceName.trim()) {
      errors.workspaceName = 'Workspace name is required.';
    } else if (workspaceName.trim().length < 2 || workspaceName.trim().length > 100) {
      errors.workspaceName = 'Workspace name must be between 2 and 100 characters.';
    }

    if (workspaceDescription.trim() && workspaceDescription.trim().length > 2000) {
      errors.workspaceDescription = 'Workspace description must not exceed 2000 characters.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // Client-side form validation for Tab 4 (Connected Links)
  const validateConnectedTab = (): boolean => {
    const errors: Record<string, string> = {};

    if (linkedinUrl.trim()) {
      if (!URL_REGEX.test(linkedinUrl.trim()) || linkedinUrl.trim().length > 500) {
        errors.linkedinUrl = 'Enter a valid LinkedIn URL starting with https://';
      }
    }

    if (githubUrl.trim()) {
      if (!URL_REGEX.test(githubUrl.trim()) || githubUrl.trim().length > 500) {
        errors.githubUrl = 'Enter a valid GitHub URL starting with https://';
      }
    }

    if (facebookUrl.trim()) {
      if (!URL_REGEX.test(facebookUrl.trim()) || facebookUrl.trim().length > 500) {
        errors.facebookUrl = 'Enter a valid Facebook URL starting with https://';
      }
    }

    if (xUrl.trim()) {
      if (!URL_REGEX.test(xUrl.trim()) || xUrl.trim().length > 500) {
        errors.xUrl = 'Enter a valid X (Twitter) URL starting with https://';
      }
    }

    if (instagramUrl.trim()) {
      if (!URL_REGEX.test(instagramUrl.trim()) || instagramUrl.trim().length > 500) {
        errors.instagramUrl = 'Enter a valid Instagram URL starting with https://';
      }
    }

    if (websiteUrl.trim()) {
      if (!URL_REGEX.test(websiteUrl.trim()) || websiteUrl.trim().length > 500) {
        errors.websiteUrl = 'Enter a valid Website URL starting with http:// or https://';
      }
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // Handle Save Profile
  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();

    let isValid = true;
    if (activeTab === 'bio') isValid = validateBioTab();
    else if (activeTab === 'ai-context') isValid = validateAiContextTab();
    else if (activeTab === 'connected') isValid = validateConnectedTab();

    if (!isValid) {
      toast.error('Please resolve the highlighted validation errors before saving.', 'Validation Error');
      return;
    }

    if (!user?.userId) {
      toast.error('User authentication context is missing. Please log in again.', 'Authentication Error');
      return;
    }

    try {
      const resultAction = await dispatch(
        updateProfile({
          authUserId: user.userId,
          firstName: sanitizeInputString(firstName).trim(),
          lastName: sanitizeInputString(lastName).trim(),
          displayName: sanitizeInputString(displayName).trim() || `${sanitizeInputString(firstName)} ${sanitizeInputString(lastName)}`.trim(),
          avatarUrl: avatarUrl.trim(),
          jobTitle: sanitizeInputString(jobTitle).trim(),
          department: sanitizeInputString(department).trim(),
          organization: sanitizeInputString(organization).trim(),
          location: sanitizeInputString(location).trim(),
          secondaryEmail: sanitizeInputString(secondaryEmail).trim(),
          phoneNumber: phoneNumber.trim(),
          education: sanitizeInputString(education).trim(),
          expertise: expertiseTags.map(sanitizeInputString).join(', '),
          skills: skillsTags.map(sanitizeInputString).join(', '),
          interests: interestsTags.map(sanitizeInputString).join(', '),
          hobbies: hobbiesTags.map(sanitizeInputString).join(', '),
          aiPersonaContext: sanitizeInputString(aiPersonaContext).trim(),
          communicationStyle,
          linkedinUrl: linkedinUrl.trim(),
          githubUrl: githubUrl.trim(),
          websiteUrl: websiteUrl.trim(),
          facebookUrl: facebookUrl.trim(),
          xUrl: xUrl.trim(),
          instagramUrl: instagramUrl.trim(),
          bio: sanitizeInputString(bio).trim(),
        })
      );

      if (updateProfile.fulfilled.match(resultAction)) {
        setFieldErrors({});
        toast.success('Your profile parameters have been saved and synchronized.', 'Profile Saved');
      } else {
        const errorMsg = (resultAction.payload as string) || 'Failed to save profile changes.';
        toast.error(errorMsg, 'Save Failed');
      }
    } catch (err: any) {
      toast.error(err.message || 'An unexpected error occurred while saving.', 'Save Error');
    }
  };

  // Handle Workspace Save
  const handleSaveWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateWorkspaceTab()) {
      toast.error('Please fix the workspace validation errors.', 'Validation Error');
      return;
    }

    const wsId = currentWorkspace?.workspaceId || (workspaces[0] ? workspaces[0].workspaceId : null);
    if (!wsId) {
      toast.error('No active workspace identified.', 'Workspace Error');
      return;
    }

    setIsUpdatingWorkspace(true);
    try {
      const resultAction = await dispatch(
        updateWorkspaceDetails({
          workspaceId: wsId,
          name: sanitizeInputString(workspaceName).trim(),
          description: sanitizeInputString(workspaceDescription).trim(),
        })
      );

      if (updateWorkspaceDetails.fulfilled.match(resultAction)) {
        setFieldErrors({});
        toast.success('Workspace parameters updated and synchronized.', 'Workspace Saved');
      } else {
        const errorMsg = (resultAction.payload as string) || 'Failed to update workspace parameters.';
        toast.error(errorMsg, 'Update Failed');
      }
    } catch (err: any) {
      toast.error(err.message || 'Error updating workspace configuration.', 'Update Error');
    } finally {
      setIsUpdatingWorkspace(false);
    }
  };

  const aiScore = calculateAiReadiness();

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-20">
      {/* Header Banner */}
      <section className="relative overflow-hidden rounded-2xl bg-card border border-border p-6 md:p-8 shadow-xs">
        <div className="absolute top-0 right-0 w-96 h-96 bg-primary/5 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        
        <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6 relative z-10">
          <div className="flex flex-col sm:flex-row items-center sm:items-start gap-5 text-center sm:text-left">
            
            {/* Avatar with Cloudinary upload trigger */}
            <div className="relative group shrink-0">
              <div className="w-24 h-24 rounded-2xl overflow-hidden bg-primary/10 border-2 border-primary/30 flex items-center justify-center font-bold text-2xl text-primary shadow-md relative">
                {avatarUrl ? (
                  <img src={avatarUrl} alt="Avatar" className="w-full h-full object-cover" />
                ) : (
                  <span>{(firstName?.slice(0, 1) + lastName?.slice(0, 1)).toUpperCase() || (user?.email?.slice(0, 2).toUpperCase()) || 'OP'}</span>
                )}

                {/* Visible Loading / Processing Overlay on Photo */}
                {isUploadingAvatar && (
                  <div className="absolute inset-0 bg-background/85 backdrop-blur-xs flex flex-col items-center justify-center gap-1.5 z-20 animate-in fade-in duration-200">
                    <Loader2 className="w-7 h-7 text-primary animate-spin" />
                    <span className="text-[9px] font-mono text-primary font-bold tracking-wider uppercase">Uploading</span>
                  </div>
                )}
              </div>

              <label 
                htmlFor="avatar-file-input"
                className={`absolute -bottom-2 -right-2 p-2 bg-primary text-primary-foreground rounded-xl shadow-md cursor-pointer hover:opacity-90 active:scale-95 transition-all z-30 ${
                  isUploadingAvatar ? 'pointer-events-none opacity-50' : ''
                }`}
                title="Upload Photo"
              >
                {isUploadingAvatar ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Camera className="w-3.5 h-3.5" />}
                <input 
                  ref={fileInputRef}
                  id="avatar-file-input" 
                  type="file" 
                  accept="image/jpeg,image/png,image/webp,image/gif" 
                  className="hidden" 
                  onChange={handleAvatarUpload}
                  disabled={isUploadingAvatar}
                />
              </label>
            </div>

            {/* Profile Identity Details */}
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2">
                <h1 className="font-serif text-2xl md:text-3xl font-bold text-foreground tracking-tight">
                  {displayName || (firstName ? `${firstName} ${lastName}`.trim() : user?.email || 'User Account')}
                </h1>
                {jobTitle && (
                  <span className="bg-primary/15 text-primary text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider border border-primary/20">
                    {jobTitle}
                  </span>
                )}
              </div>

              <p className="text-xs text-muted-foreground flex items-center justify-center sm:justify-start gap-3">
                <span className="flex items-center gap-1 font-mono">
                  <Mail className="w-3.5 h-3.5 text-primary" />
                  {user?.email || 'user@rolesync.ai'}
                </span>
                {location && (
                  <span className="flex items-center gap-1">
                    <MapPin className="w-3.5 h-3.5 text-muted-foreground" />
                    {location}
                  </span>
                )}
              </p>

              {(organization || department) && (
                <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2 pt-1">
                  {organization && (
                    <span className="text-[10px] font-mono bg-muted/80 text-muted-foreground px-2.5 py-0.5 rounded-md border border-border/60">
                      Org: <strong className="text-foreground">{organization}</strong>
                    </span>
                  )}
                  {department && (
                    <span className="text-[10px] font-mono bg-muted/80 text-muted-foreground px-2.5 py-0.5 rounded-md border border-border/60">
                      Dept: <strong className="text-foreground">{department}</strong>
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* AI Persona Readiness Index Card */}
          <div className="w-full lg:w-72 bg-muted/35 border border-border/80 rounded-xl p-4 shadow-2xs space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <Bot className="w-3.5 h-3.5 text-primary" />
                AI Agent Context Score
              </span>
              <span className="font-mono text-xs font-bold text-primary">{aiScore}%</span>
            </div>
            
            <div className="w-full bg-border/60 h-2 rounded-full overflow-hidden">
              <div 
                className="bg-primary h-full rounded-full transition-all duration-700 ease-out"
                style={{ width: `${aiScore}%` }}
              ></div>
            </div>

            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {aiScore >= 80 
                ? 'Your AI profile is fully configured for deep context-aware automations.'
                : 'Complete your profile bio, skills, and persona context to improve AI accuracy.'}
            </p>
          </div>
        </div>
      </section>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-border/80 pb-px overflow-x-auto">
        {[
          { id: 'bio', label: 'User Bio-Data & Education', icon: User },
          { id: 'ai-context', label: 'AI Agent Context & Expertise', icon: Bot },
          { id: 'workspace', label: 'Workspace Configuration', icon: Building2 },
          { id: 'connected', label: 'External Links & Identifiers', icon: Link2 },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id as any);
                setFieldErrors({});
              }}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-t-xl text-xs font-semibold transition-all border-b-2 whitespace-nowrap cursor-pointer ${
                isActive
                  ? 'border-primary text-primary bg-primary/5 font-bold'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/40'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* TAB 1: USER BIO-DATA & EDUCATION */}
      {activeTab === 'bio' && (
        <form onSubmit={handleSaveProfile} className="space-y-6 animate-in fade-in duration-300" noValidate>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Identity & Contact Card */}
            <div className="lg:col-span-2 bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-6">
              <div className="border-b border-border/60 pb-3 flex items-center justify-between">
                <h3 className="font-serif text-lg font-bold text-foreground flex items-center gap-2">
                  <User className="w-5 h-5 text-primary" />
                  <span>Personal & Professional Identity</span>
                </h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Input
                  label="First Name *"
                  id="profile-first-name"
                  type="text"
                  value={firstName}
                  maxLength={50}
                  error={fieldErrors.firstName}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setFirstName(e.target.value);
                    if (fieldErrors.firstName) setFieldErrors(prev => ({ ...prev, firstName: '' }));
                  }}
                  placeholder="Enter your first name (e.g. Rohan)"
                  required
                />

                <Input
                  label="Last Name *"
                  id="profile-last-name"
                  type="text"
                  value={lastName}
                  maxLength={50}
                  error={fieldErrors.lastName}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setLastName(e.target.value);
                    if (fieldErrors.lastName) setFieldErrors(prev => ({ ...prev, lastName: '' }));
                  }}
                  placeholder="Enter your last name (e.g. Balami)"
                  required
                />

                <Input
                  label="Display Name / Alias"
                  id="profile-display-name"
                  type="text"
                  value={displayName}
                  maxLength={100}
                  error={fieldErrors.displayName}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setDisplayName(e.target.value);
                    if (fieldErrors.displayName) setFieldErrors(prev => ({ ...prev, displayName: '' }));
                  }}
                  placeholder="Enter your preferred display name or alias"
                />

                <Input
                  label="Job Title / Role"
                  id="profile-job-title"
                  type="text"
                  value={jobTitle}
                  maxLength={100}
                  error={fieldErrors.jobTitle}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setJobTitle(e.target.value);
                    if (fieldErrors.jobTitle) setFieldErrors(prev => ({ ...prev, jobTitle: '' }));
                  }}
                  placeholder="Enter your job title or role (e.g. Senior Software Engineer)"
                />

                <Input
                  label="Department / Unit"
                  id="profile-department"
                  type="text"
                  value={department}
                  maxLength={100}
                  error={fieldErrors.department}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setDepartment(e.target.value);
                    if (fieldErrors.department) setFieldErrors(prev => ({ ...prev, department: '' }));
                  }}
                  placeholder="Enter your department or team (e.g. Engineering)"
                />

                <Input
                  label="Organization / Company"
                  id="profile-organization"
                  type="text"
                  value={organization}
                  maxLength={100}
                  error={fieldErrors.organization}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setOrganization(e.target.value);
                    if (fieldErrors.organization) setFieldErrors(prev => ({ ...prev, organization: '' }));
                  }}
                  placeholder="Enter your organization or company name"
                />

                <Input
                  label="Location / Region"
                  id="profile-location"
                  type="text"
                  value={location}
                  maxLength={100}
                  error={fieldErrors.location}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setLocation(e.target.value);
                    if (fieldErrors.location) setFieldErrors(prev => ({ ...prev, location: '' }));
                  }}
                  placeholder="Enter your location (e.g. San Francisco, CA / Remote)"
                  leftElement={<MapPin className="w-4 h-4" />}
                />

                <Input
                  label="Phone Number"
                  id="profile-phone"
                  type="tel"
                  value={phoneNumber}
                  maxLength={25}
                  error={fieldErrors.phoneNumber}
                  onChange={handlePhoneChange}
                  placeholder="Enter your phone number (e.g. +1 555 234 5678)"
                  helperText="Digits and +, -, ( ) accepted"
                  leftElement={<Phone className="w-4 h-4" />}
                />
              </div>

              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <Input
                    label="Primary Authentication Email (Read-Only)"
                    id="profile-primary-email"
                    type="email"
                    value={user?.email || ''}
                    disabled
                    className="bg-muted/40 font-mono text-xs cursor-not-allowed opacity-80"
                    leftElement={<Mail className="w-4 h-4" />}
                  />

                  <Input
                    label="Secondary / Work Email"
                    id="profile-secondary-email"
                    type="email"
                    value={secondaryEmail}
                    maxLength={100}
                    error={fieldErrors.secondaryEmail}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                      setSecondaryEmail(e.target.value);
                      if (fieldErrors.secondaryEmail) setFieldErrors(prev => ({ ...prev, secondaryEmail: '' }));
                    }}
                    placeholder="Enter an alternate email address (e.g. work@company.com)"
                    leftElement={<Mail className="w-4 h-4" />}
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground">
                      Bio & Professional Summary
                    </label>
                    <span className="text-[10px] font-mono text-muted-foreground">
                      {bio.length} / 3000 chars
                    </span>
                  </div>
                  <textarea
                    rows={7}
                    maxLength={3000}
                    value={bio}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                      setBio(e.target.value);
                      if (fieldErrors.bio) setFieldErrors(prev => ({ ...prev, bio: '' }));
                    }}
                    placeholder="Write a brief overview of your background, experience, and leadership focus..."
                    className={`w-full px-4 py-2.5 bg-background border rounded-xl text-sm focus:outline-none transition-all font-sans leading-relaxed ${
                      fieldErrors.bio
                        ? 'border-destructive focus:ring-2 focus:ring-destructive/10'
                        : 'border-border focus:border-primary/50 focus:ring-2 focus:ring-primary/10'
                    }`}
                  />
                  {fieldErrors.bio && (
                    <p className="text-[11px] text-destructive font-medium mt-1">{fieldErrors.bio}</p>
                  )}
                </div>

                <div className="pt-2 flex justify-end">
                  <Button
                    type="submit"
                    disabled={!isBioTabDirty || isLoading || isUploadingAvatar}
                    isLoading={isLoading}
                    loadingText="Saving..."
                    icon={<Save className="w-4 h-4" />}
                    className="w-auto px-6 py-2.5 text-xs font-bold rounded-xl cursor-pointer disabled:opacity-10 disabled:cursor-not-allowed"
                  >
                    Save
                  </Button>
                </div>
              </div>
            </div>

            {/* Education & Avatar Presets Card */}
            <div className="space-y-7">
              {/* Education Card */}
              <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-4">
                <div className="border-b border-border/60 pb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <GraduationCap className="w-5 h-5 text-primary" />
                    <h3 className="font-serif text-lg font-bold text-foreground">Education & Degrees</h3>
                  </div>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {education.length} / 3000
                  </span>
                </div>

                <div className="space-y-3">
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground">
                    Academic Background
                  </label>
                  <textarea
                    rows={5}
                    maxLength={3000}
                    value={education}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                      setEducation(e.target.value);
                      if (fieldErrors.education) setFieldErrors(prev => ({ ...prev, education: '' }));
                    }}
                    placeholder="e.g. B.S. in Computer Science, University (Year)"
                    className={`w-full px-3.5 py-2.5 bg-background border rounded-xl text-xs focus:outline-none transition-all leading-relaxed ${
                      fieldErrors.education
                        ? 'border-destructive focus:ring-2 focus:ring-destructive/10'
                        : 'border-border focus:border-primary/50 focus:ring-2 focus:ring-primary/10'
                    }`}
                  />
                  {fieldErrors.education && (
                    <p className="text-[11px] text-destructive font-medium">{fieldErrors.education}</p>
                  )}
                </div>
              </div>

              {/* Photo Avatar Preset Chooser & Direct Cloudinary URL Hosting */}
              <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-4">
                <div className="border-b border-border/60 pb-3 flex items-center justify-between">
                  <h4 className="font-serif text-sm font-bold text-foreground">Preset Avatars</h4>
                  <span className="text-[10px] font-mono text-muted-foreground">Instant Selection</span>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  {AVATAR_PRESETS.map((preset, idx) => (
                    <button
                      key={idx}
                      type="button"
                      disabled={isUploadingAvatar}
                      onClick={() => handleHostRemoteImageUrl(preset)}
                      className={`relative w-full aspect-square rounded-xl overflow-hidden border-2 cursor-pointer transition-all hover:scale-105 ${
                        avatarUrl === preset ? 'border-primary shadow-xs ring-2 ring-primary/20' : 'border-border/60 opacity-70 hover:opacity-100'
                      }`}
                    >
                      <img src={preset} alt="Preset" className="w-full h-full object-cover" />
                    </button>
                  ))}
                </div>

                <div className="pt-2 space-y-2">
                  <Input
                    label="Or Direct Image URL"
                    id="profile-avatar-url"
                    type="url"
                    value={customImageUrl}
                    error={fieldErrors.avatarUrl}
                    maxLength={1000}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                      const val = e.target.value;
                      setCustomImageUrl(val);
                      if (val.trim()) {
                        setAvatarUrl(val.trim());
                      }
                      if (fieldErrors.avatarUrl) setFieldErrors(prev => ({ ...prev, avatarUrl: '' }));
                    }}
                    onBlur={() => {
                      if (customImageUrl && (customImageUrl.startsWith('http://') || customImageUrl.startsWith('https://'))) {
                        handleHostRemoteImageUrl(customImageUrl, true);
                      }
                    }}
                    placeholder="https://example.com/photo.jpg or direct image link..."
                    className="text-xs font-mono"
                  />
                  
                  {isUploadingAvatar && (
                    <div className="flex items-center gap-2 text-xs text-primary font-mono pt-1">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Processing and securing image...</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

          </div>
        </form>
      )}

      {/* TAB 2: AI AGENT CONTEXT & EXPERTISE */}
      {activeTab === 'ai-context' && (
        <form onSubmit={handleSaveProfile} className="space-y-6 animate-in fade-in duration-300" noValidate>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* AI Persona Prompt Context */}
            <div className="lg:col-span-2 bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-6">
              <div className="border-b border-border/60 pb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Bot className="w-5 h-5 text-primary animate-pulse" />
                  <h3 className="font-serif text-lg font-bold text-foreground">AI Agent Persona & Instructions</h3>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground">
                    Custom AI Agent Context (Who are you to the AI?)
                  </label>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {aiPersonaContext.length} / 5000 chars
                  </span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Provide guidance on your role, priorities, and how connected AI agents should interpret your queries, formulate summaries, and structure deliverables.
                </p>
                <textarea
                  rows={4}
                  maxLength={5000}
                  value={aiPersonaContext}
                  onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                    setAiPersonaContext(e.target.value);
                    if (fieldErrors.aiPersonaContext) setFieldErrors(prev => ({ ...prev, aiPersonaContext: '' }));
                  }}
                  placeholder="e.g. Always emphasize ROI, concise milestones, and technical differentiation. Provide actionable bullet points..."
                  className={`w-full px-4 py-3 bg-background border rounded-xl text-xs focus:outline-none transition-all leading-relaxed font-sans ${
                    fieldErrors.aiPersonaContext
                      ? 'border-destructive focus:ring-2 focus:ring-destructive/10'
                      : 'border-border focus:border-primary/50 focus:ring-2 focus:ring-primary/10'
                  }`}
                />
                {fieldErrors.aiPersonaContext && (
                  <p className="text-[11px] text-destructive font-medium">{fieldErrors.aiPersonaContext}</p>
                )}
              </div>

              {/* Working Style & Autonomy Selectors */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <div>
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground mb-1.5">
                    Preferred Communication Style
                  </label>
                  <select
                    value={communicationStyle}
                    onChange={(e) => setCommunicationStyle(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-background border border-border rounded-xl text-xs focus:outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all font-medium"
                  >
                    <option value="Strategic & Concise">Strategic & Concise (Executive style)</option>
                    <option value="Technical & Analytical">Technical & Analytical (Deep citations)</option>
                    <option value="Comprehensive & Detailed">Comprehensive & Detailed (Full breakdowns)</option>
                    <option value="Action-Oriented">Action-Oriented (Next steps only)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground mb-1.5">
                    Agent Autonomy Profile
                  </label>
                  <select
                    value={autonomyLevel}
                    onChange={(e) => setAutonomyLevel(e.target.value)}
                    className="w-full px-3.5 py-2.5 bg-background border border-border rounded-xl text-xs focus:outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all font-medium"
                  >
                    <option value="Supervised Execution">Supervised Execution (Prompt before actions)</option>
                    <option value="Semi-Autonomous">Semi-Autonomous (Auto-draft & stage)</option>
                    <option value="Full Orchestration">Full Orchestration (Autonomous sync & post)</option>
                  </select>
                </div>
              </div>

              {/* Expertise Matrix Tag Manager */}
              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground">
                    Domain Expertise & Specializations
                  </label>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {expertiseTags.length}/25 tags
                  </span>
                </div>
                <div className="flex flex-wrap gap-2 mb-2">
                  {expertiseTags.map((tag, idx) => (
                    <span
                      key={idx}
                      className="inline-flex items-center gap-1.5 px-3 py-1 bg-primary/10 text-primary border border-primary/20 rounded-lg text-xs font-semibold"
                    >
                      <span>{tag}</span>
                      <button
                        type="button"
                        onClick={() => removeTag(idx, expertiseTags, setExpertiseTags)}
                        className="hover:text-destructive transition-colors cursor-pointer"
                        title="Remove tag"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    maxLength={50}
                    value={newExpertiseTag}
                    onChange={(e) => setNewExpertiseTag(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        addTag(newExpertiseTag, expertiseTags, setExpertiseTags, setNewExpertiseTag);
                      }
                    }}
                    placeholder="Add domain expertise (e.g. Cloud Architecture)..."
                    className="flex-1 px-3.5 py-2 bg-background border border-border rounded-xl text-xs focus:outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => addTag(newExpertiseTag, expertiseTags, setExpertiseTags, setNewExpertiseTag)}
                    className="w-auto px-4 text-xs font-semibold rounded-xl cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add</span>
                  </Button>
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <Button
                  type="submit"
                  disabled={!isAiContextTabDirty || isLoading}
                  isLoading={isLoading}
                  loadingText="Saving..."
                  icon={<Save className="w-4 h-4" />}
                  className="w-auto px-6 py-2.5 text-xs font-bold rounded-xl cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Save
                </Button>
              </div>
            </div>

            {/* Skills, Interests & Hobbies Matrix */}
            <div className="space-y-7">
              
              {/* Technical & Operational Skills */}
              <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-4">
                <div className="border-b border-border/60 pb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Award className="w-5 h-5 text-primary" />
                    <h3 className="font-serif text-lg font-bold text-foreground">Skills & Tools</h3>
                  </div>
                  <span className="text-[10px] font-mono text-muted-foreground">{skillsTags.length}/25</span>
                </div>

                <div className="flex flex-wrap gap-1.5 mb-2">
                  {skillsTags.map((tag, idx) => (
                    <span
                      key={idx}
                      className="inline-flex items-center gap-1 px-2.5 py-0.5 bg-muted border border-border/80 rounded-md text-[11px] font-mono text-foreground"
                    >
                      <span>{tag}</span>
                      <button
                        type="button"
                        onClick={() => removeTag(idx, skillsTags, setSkillsTags)}
                        className="hover:text-destructive transition-colors cursor-pointer"
                      >
                        <X className="w-2.5 h-2.5" />
                      </button>
                    </span>
                  ))}
                </div>

                <div className="flex gap-2">
                  <input
                    type="text"
                    maxLength={50}
                    value={newSkillTag}
                    onChange={(e) => setNewSkillTag(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        addTag(newSkillTag, skillsTags, setSkillsTags, setNewSkillTag);
                      }
                    }}
                    placeholder="Add skill (e.g. Python, SQL)..."
                    className="flex-1 px-3 py-1.5 bg-background border border-border rounded-xl text-xs focus:outline-none focus:border-primary/50"
                  />
                  <button
                    type="button"
                    onClick={() => addTag(newSkillTag, skillsTags, setSkillsTags, setNewSkillTag)}
                    className="p-2 bg-primary/10 text-primary border border-primary/20 rounded-xl hover:bg-primary/20 transition-all cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Interests & Hobbies */}
              <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-4">
                <div className="border-b border-border/60 pb-3 flex items-center gap-2">
                  <Heart className="w-5 h-5 text-primary" />
                  <h3 className="font-serif text-lg font-bold text-foreground">Interests & Hobbies</h3>
                </div>

                <div className="space-y-8">
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="block text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
                        Professional Interests
                      </label>
                      <span className="text-[9px] font-mono text-muted-foreground">{interestsTags.length}/25</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {interestsTags.map((tag, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center gap-1 px-2.5 py-0.5 bg-secondary/20 text-foreground border border-border/60 rounded-md text-[10px]"
                        >
                          <span>{tag}</span>
                          <button
                            type="button"
                            onClick={() => removeTag(idx, interestsTags, setInterestsTags)}
                            className="hover:text-destructive transition-colors cursor-pointer"
                          >
                            <X className="w-2.5 h-2.5" />
                          </button>
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        maxLength={50}
                        value={newInterestTag}
                        onChange={(e) => setNewInterestTag(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            addTag(newInterestTag, interestsTags, setInterestsTags, setNewInterestTag);
                          }
                        }}
                        placeholder="Add interest (e.g. AI Ethics)..."
                        className="flex-1 px-3 py-1.5 bg-background border border-border rounded-xl text-xs focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => addTag(newInterestTag, interestsTags, setInterestsTags, setNewInterestTag)}
                        className="p-2 bg-primary/10 text-primary border border-primary/20 rounded-xl cursor-pointer"
                      >
                        <Plus className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="block text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
                        Hobbies & Personal Passions
                      </label>
                      <span className="text-[9px] font-mono text-muted-foreground">{hobbiesTags.length}/25</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {hobbiesTags.map((tag, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center gap-1 px-2.5 py-0.5 bg-muted border border-border/80 rounded-md text-[10px]"
                        >
                          <span>{tag}</span>
                          <button
                            type="button"
                            onClick={() => removeTag(idx, hobbiesTags, setHobbiesTags)}
                            className="hover:text-destructive transition-colors cursor-pointer"
                          >
                            <X className="w-2.5 h-2.5" />
                          </button>
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        maxLength={50}
                        value={newHobbyTag}
                        onChange={(e) => setNewHobbyTag(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            addTag(newHobbyTag, hobbiesTags, setHobbiesTags, setNewHobbyTag);
                          }
                        }}
                        placeholder="Add hobby (e.g. Reading, Hiking)..."
                        className="flex-1 px-3 py-1.5 bg-background border border-border rounded-xl text-xs focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => addTag(newHobbyTag, hobbiesTags, setHobbiesTags, setNewHobbyTag)}
                        className="p-2 bg-primary/10 text-primary border border-primary/20 rounded-xl cursor-pointer"
                      >
                        <Plus className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>

            </div>

          </div>
        </form>
      )}

      {/* TAB 3: WORKSPACE CONFIGURATION */}
      {activeTab === 'workspace' && (
        <form onSubmit={handleSaveWorkspace} className="space-y-6 animate-in fade-in duration-300" noValidate>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Main Workspace Configuration Form */}
            <div className="lg:col-span-2 bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-6">
              <div className="border-b border-border/60 pb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Building2 className="w-5 h-5 text-primary" />
                  <h3 className="font-serif text-lg font-bold text-foreground">Workspace Parameters</h3>
                </div>
              </div>

              <div className="space-y-4">
                <Input
                  label="Workspace Name *"
                  id="profile-workspace-name"
                  type="text"
                  value={workspaceName}
                  maxLength={100}
                  error={fieldErrors.workspaceName}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    setWorkspaceName(e.target.value);
                    if (fieldErrors.workspaceName) setFieldErrors(prev => ({ ...prev, workspaceName: '' }));
                  }}
                  placeholder="Enter workspace name (e.g. Sales Workspace)"
                  required
                />

                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="block text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground">
                      Workspace Description & Mission
                    </label>
                    <span className="text-[10px] font-mono text-muted-foreground">
                      {workspaceDescription.length} / 2000 chars
                    </span>
                  </div>
                  <textarea
                    rows={4}
                    maxLength={2000}
                    value={workspaceDescription}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                      setWorkspaceDescription(e.target.value);
                      if (fieldErrors.workspaceDescription) setFieldErrors(prev => ({ ...prev, workspaceDescription: '' }));
                    }}
                    placeholder="Describe the objective and target pipelines for this workspace..."
                    className={`w-full px-4 py-2.5 bg-background border rounded-xl text-sm focus:outline-none transition-all font-sans leading-relaxed ${
                      fieldErrors.workspaceDescription
                        ? 'border-destructive focus:ring-2 focus:ring-destructive/10'
                        : 'border-border focus:border-primary/50 focus:ring-2 focus:ring-primary/10'
                    }`}
                  />
                  {fieldErrors.workspaceDescription && (
                    <p className="text-[11px] text-destructive font-medium mt-1">{fieldErrors.workspaceDescription}</p>
                  )}
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <Button
                  type="submit"
                  disabled={!isWorkspaceTabDirty || isUpdatingWorkspace}
                  isLoading={isUpdatingWorkspace}
                  loadingText="Saving..."
                  icon={<Save className="w-4 h-4" />}
                  className="w-auto px-6 py-2.5 text-xs font-bold rounded-xl cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Save
                </Button>
              </div>
            </div>

            {/* Workspace Membership Details */}
            <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-6">
              <div className="border-b border-border/60 pb-3 flex items-center gap-2">
                <Layers className="w-5 h-5 text-primary" />
                <h3 className="font-serif text-lg font-bold text-foreground">Active Workspaces</h3>
              </div>

              <div className="space-y-3">
                {workspaces.map((ws) => (
                  <div 
                    key={ws.workspaceId}
                    className="p-4 bg-muted/40 border border-border/60 rounded-xl space-y-1.5"
                  >
                    <div className="flex items-center justify-between">
                      <h5 className="font-bold text-xs text-foreground">{ws.name}</h5>
                      <span className="text-[9px] font-mono bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 rounded font-bold uppercase">
                        OWNER
                      </span>
                    </div>
                    {ws.description && (
                      <p className="text-[11px] text-muted-foreground line-clamp-2 leading-relaxed">
                        {ws.description}
                      </p>
                    )}
                    <p className="text-[9px] font-mono text-muted-foreground/70 pt-1">
                      ID: {ws.workspaceId}
                    </p>
                  </div>
                ))}
              </div>

              <div className="p-4 bg-primary/5 border border-primary/15 rounded-xl space-y-2">
                <p className="text-xs font-bold text-foreground flex items-center gap-1.5">
                  <ShieldCheck className="w-4 h-4 text-primary" />
                  <span>Role-Based Access</span>
                </p>
                <p className="text-[10px] text-muted-foreground leading-relaxed">
                  Your identity holds Owner permissions across this workspace.
                </p>
              </div>
            </div>

          </div>
        </form>
      )}

      {/* TAB 4: EXTERNAL LINKS & IDENTIFIERS */}
      {activeTab === 'connected' && (
        <form onSubmit={handleSaveProfile} className="space-y-6 animate-in fade-in duration-300 max-w-4xl" noValidate>
          <div className="bg-card border border-border p-6 rounded-2xl shadow-2xs space-y-6">
            <div className="border-b border-border/60 pb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Link2 className="w-5 h-5 text-primary" />
                <h3 className="font-serif text-lg font-bold text-foreground">Social & Professional Links</h3>
              </div>
            </div>

            <div className="space-y-4">
              <Input
                label="LinkedIn Profile URL"
                id="profile-linkedin"
                type="url"
                value={linkedinUrl}
                maxLength={500}
                error={fieldErrors.linkedinUrl}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setLinkedinUrl(e.target.value);
                  if (fieldErrors.linkedinUrl) setFieldErrors(prev => ({ ...prev, linkedinUrl: '' }));
                }}
                placeholder="https://linkedin.com/in/your-profile"
                helperText="Must start with https://"
                leftElement={<LinkedinIcon className="w-4 h-4 text-primary" />}
              />

              <Input
                label="GitHub Profile URL"
                id="profile-github"
                type="url"
                value={githubUrl}
                maxLength={500}
                error={fieldErrors.githubUrl}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setGithubUrl(e.target.value);
                  if (fieldErrors.githubUrl) setFieldErrors(prev => ({ ...prev, githubUrl: '' }));
                }}
                placeholder="https://github.com/your-username"
                helperText="Must start with https://"
                leftElement={<GithubIcon className="w-4 h-4 text-primary" />}
              />

              <Input
                label="Facebook Profile URL"
                id="profile-facebook"
                type="url"
                value={facebookUrl}
                maxLength={500}
                error={fieldErrors.facebookUrl}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setFacebookUrl(e.target.value);
                  if (fieldErrors.facebookUrl) setFieldErrors(prev => ({ ...prev, facebookUrl: '' }));
                }}
                placeholder="https://facebook.com/your.username"
                helperText="Must start with https://"
                leftElement={<FacebookIcon className="w-4 h-4 text-primary" />}
              />

              <Input
                label="X (Twitter) Profile URL"
                id="profile-x"
                type="url"
                value={xUrl}
                maxLength={500}
                error={fieldErrors.xUrl}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setXUrl(e.target.value);
                  if (fieldErrors.xUrl) setFieldErrors(prev => ({ ...prev, xUrl: '' }));
                }}
                placeholder="https://x.com/your_handle"
                helperText="Must start with https://"
                leftElement={<XIcon className="w-4 h-4 text-primary" />}
              />

              <Input
                label="Instagram Profile URL"
                id="profile-instagram"
                type="url"
                value={instagramUrl}
                maxLength={500}
                error={fieldErrors.instagramUrl}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setInstagramUrl(e.target.value);
                  if (fieldErrors.instagramUrl) setFieldErrors(prev => ({ ...prev, instagramUrl: '' }));
                }}
                placeholder="https://instagram.com/your_username"
                helperText="Must start with https://"
                leftElement={<InstagramIcon className="w-4 h-4 text-primary" />}
              />

              <Input
                label="Portfolio / Personal Website"
                id="profile-website"
                type="url"
                value={websiteUrl}
                maxLength={500}
                error={fieldErrors.websiteUrl}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setWebsiteUrl(e.target.value);
                  if (fieldErrors.websiteUrl) setFieldErrors(prev => ({ ...prev, websiteUrl: '' }));
                }}
                placeholder="https://yourwebsite.com"
                helperText="Must start with http:// or https://"
                leftElement={<Globe className="w-4 h-4 text-primary" />}
              />
            </div>

            <div className="pt-2 flex justify-end">
              <Button
                type="submit"
                disabled={!isConnectedTabDirty || isLoading}
                isLoading={isLoading}
                loadingText="Saving..."
                icon={<Save className="w-4 h-4" />}
                className="w-auto px-6 py-2.5 text-xs font-bold rounded-xl cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Save
              </Button>
            </div>
          </div>
        </form>
      )}

    </div>
  );
};

export default Profile;

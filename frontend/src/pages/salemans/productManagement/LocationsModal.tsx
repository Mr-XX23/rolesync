import React, { useState } from 'react';
import {
  X,
  Building2,
  Plus,
  CheckCircle2,
  AlertCircle,
  Loader2,
  MapPin,
  Pencil,
  Trash2,
  Check,
  Store,
  Truck,
  ShieldAlert,
  Sparkles,
} from 'lucide-react';
import { catalogApi, type Location, type LocationCreate } from '../../../api/catalogApi';
import { useToast } from '../../../context/ToastContext';

interface LocationsModalProps {
  isOpen: boolean;
  onClose: () => void;
  locations: Location[];
  onLocationsUpdated: () => void;
}

// Map named string priority tiers to numeric order for backend priority sorting
const PRIORITY_TIER_MAP: Record<string, number> = {
  primary: 1,
  highest: 1,
  urgent: 1,
  first: 1,
  high: 2,
  normal: 3,
  standard: 3,
  medium: 3,
  secondary: 4,
  low: 5,
  backup: 5,
  last: 5,
};

function resolveNumericPriority(label: string): number {
  const normalized = label.trim().toLowerCase();
  if (PRIORITY_TIER_MAP[normalized] !== undefined) {
    return PRIORITY_TIER_MAP[normalized];
  }
  // Default to tier 10 for custom string labels
  return 10;
}

function sanitizeText(val: string): string {
  return val.replace(/<[^>]*>?/gm, '').trim();
}

export const LocationsModal: React.FC<LocationsModalProps> = ({
  isOpen,
  onClose,
  locations,
  onLocationsUpdated,
}) => {
  const toast = useToast();

  const [isOpenForm, setIsOpenForm] = useState<boolean>(false);
  const [editingLocationId, setEditingLocationId] = useState<string | null>(null);

  // Form fields
  const [name, setName] = useState<string>('');
  const [type, setType] = useState<'WAREHOUSE' | 'STORE' | 'SUPPLIER' | 'IN_TRANSIT'>('WAREHOUSE');
  const [sellable, setSellable] = useState<boolean>(true);
  const [priorityLabel, setPriorityLabel] = useState<string>('Primary');
  const [city, setCity] = useState<string>('');
  const [country, setCountry] = useState<string>('');

  // States
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [deletingLocationId, setDeletingLocationId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Field errors for inline validation
  const [fieldErrors, setFieldErrors] = useState<{
    name?: string;
    priority?: string;
  }>({});

  if (!isOpen) return null;

  const resetForm = () => {
    setName('');
    setType('WAREHOUSE');
    setSellable(true);
    setPriorityLabel('Primary');
    setCity('');
    setCountry('');
    setEditingLocationId(null);
    setFieldErrors({});
    setErrorMessage(null);
    setIsOpenForm(false);
    setConfirmDeleteId(null);
  };

  const handleStartEdit = (loc: Location) => {
    setEditingLocationId(loc.id);
    setName(loc.name);
    setType(loc.type as any);
    setSellable(loc.sellable);
    
    // Priority string label from metadata or mapped fallback
    const savedPriorityLabel =
      loc.address?.priority_label ||
      (loc.priority === 1
        ? 'Primary'
        : loc.priority === 2
        ? 'High'
        : loc.priority === 3
        ? 'Normal'
        : loc.priority === 4
        ? 'Secondary'
        : loc.priority === 5
        ? 'Low'
        : `Tier ${loc.priority}`);
    
    setPriorityLabel(savedPriorityLabel);
    setCity(loc.address?.city || '');
    setCountry(loc.address?.country || '');
    setFieldErrors({});
    setErrorMessage(null);
    setIsOpenForm(true);
  };

  const validateForm = (): boolean => {
    const errors: { name?: string; priority?: string } = {};

    // 1. Name validation
    const cleanName = sanitizeText(name);
    if (!cleanName) {
      errors.name = 'Store or Warehouse Name is required.';
    } else if (cleanName.length < 2) {
      errors.name = 'Location name must be at least 2 characters.';
    } else if (cleanName.length > 100) {
      errors.name = 'Location name cannot exceed 100 characters.';
    }

    // 2. Priority validation (must be string, cannot be pure numbers)
    const cleanPriority = sanitizeText(priorityLabel);
    if (!cleanPriority) {
      errors.priority = 'Fulfillment Priority is required.';
    } else if (/^\d+$/.test(cleanPriority)) {
      errors.priority =
        'Priority must be a descriptive name (e.g. Primary, High, Normal, Secondary), numbers are not allowed.';
    } else if (cleanPriority.length < 2) {
      errors.priority = 'Priority name must be at least 2 characters.';
    } else if (cleanPriority.length > 50) {
      errors.priority = 'Priority name cannot exceed 50 characters.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateForm()) return;

    setIsSubmitting(true);
    setErrorMessage(null);

    const cleanName = sanitizeText(name);
    const cleanPriority = sanitizeText(priorityLabel);
    const cleanCity = sanitizeText(city);
    const cleanCountry = sanitizeText(country);

    const numericPriority = resolveNumericPriority(cleanPriority);

    const payload: LocationCreate = {
      name: cleanName,
      type,
      sellable,
      priority: numericPriority,
      address: {
        ...(cleanCity ? { city: cleanCity } : {}),
        ...(cleanCountry ? { country: cleanCountry } : {}),
        priority_label: cleanPriority,
      },
    };

    try {
      if (editingLocationId) {
        await catalogApi.updateLocation(editingLocationId, payload);
        toast.success(`Location "${cleanName}" updated successfully.`, 'Location Updated');
      } else {
        await catalogApi.createLocation(payload);
        toast.success(`Location "${cleanName}" created successfully.`, 'Location Added');
      }

      resetForm();
      onLocationsUpdated();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to save location.';
      setErrorMessage(msg);
      toast.error(msg, 'Action Error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (locationId: string, locationName: string) => {
    setDeletingLocationId(locationId);
    setErrorMessage(null);

    try {
      await catalogApi.deleteLocation(locationId);
      toast.success(`Location "${locationName}" was deleted.`, 'Location Deleted');
      setConfirmDeleteId(null);
      if (editingLocationId === locationId) {
        resetForm();
      }
      onLocationsUpdated();
    } catch (err: any) {
      const msg =
        err.response?.data?.detail ||
        err.message ||
        'Cannot delete location. Ensure its stock is 0.';
      setErrorMessage(msg);
      toast.error(msg, 'Delete Error');
    } finally {
      setDeletingLocationId(null);
    }
  };

  const getPriorityDisplay = (loc: Location) => {
    if (loc.address?.priority_label) {
      return loc.address.priority_label;
    }
    switch (loc.priority) {
      case 1:
        return 'Primary';
      case 2:
        return 'High';
      case 3:
        return 'Normal';
      case 4:
        return 'Secondary';
      case 5:
        return 'Low';
      default:
        return `Tier ${loc.priority}`;
    }
  };

  const getTypeIcon = (locType: string) => {
    switch (locType) {
      case 'STORE':
        return <Store className="w-4 h-4 text-sky-400" />;
      case 'IN_TRANSIT':
      case 'SUPPLIER':
        return <Truck className="w-4 h-4 text-purple-400" />;
      default:
        return <Building2 className="w-4 h-4 text-amber-400" />;
    }
  };

  const getTypeLabel = (locType: string) => {
    switch (locType) {
      case 'STORE':
        return 'Retail Store';
      case 'SUPPLIER':
        return 'Supplier Depot';
      case 'IN_TRANSIT':
        return 'In Transit Hub';
      default:
        return 'Warehouse (Central DC)';
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl bg-card border border-border/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header: Clean & Simple */}
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-card/90">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/15 border border-primary/25 flex items-center justify-center text-primary">
              <Building2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-foreground text-base">
                Inventory Locations & Stores
              </h3>
              <p className="text-xs text-muted-foreground">
                Manage your warehouses, retail shops, and stock fulfillment order
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl text-muted-foreground hover:text-foreground hover:bg-muted/70 transition-colors"
            title="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-6 overflow-y-auto">
          {/* Top Bar: Count & Add Button */}
          <div className="flex items-center justify-between">
            <div className="text-xs text-muted-foreground">
              <span className="font-bold text-foreground text-sm">{locations.length}</span> active
              inventory locations
            </div>
            <button
              onClick={() => {
                if (isOpenForm) {
                  resetForm();
                } else {
                  setIsOpenForm(true);
                }
              }}
              className="px-3.5 py-2 text-xs font-semibold rounded-xl bg-primary/10 text-primary hover:bg-primary/20 transition-colors flex items-center gap-2 border border-primary/20"
            >
              <Plus className="w-4 h-4" />
              {isOpenForm ? 'Hide Form' : 'Add New Location'}
            </button>
          </div>

          {/* Form */}
          {isOpenForm && (
            <form
              onSubmit={handleSubmit}
              className="p-5 rounded-2xl bg-muted/30 border border-border/80 space-y-4 animate-in fade-in duration-200"
            >
              <div className="flex items-center justify-between pb-1 border-b border-border/50">
                <h4 className="text-xs font-bold text-foreground uppercase tracking-wider flex items-center gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-primary" />
                  {editingLocationId ? 'Edit Inventory Location' : 'Add Inventory Location / Store'}
                </h4>
                {editingLocationId && (
                  <button
                    type="button"
                    onClick={resetForm}
                    className="text-xs text-muted-foreground hover:text-foreground underline"
                  >
                    Cancel Editing
                  </button>
                )}
              </div>

              {errorMessage && (
                <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/25 text-destructive text-xs flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{errorMessage}</span>
                </div>
              )}

              {/* Row 1: Location Name & Inventory Type */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
                    Store / Warehouse Name *
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value);
                      if (fieldErrors.name) setFieldErrors({ ...fieldErrors, name: undefined });
                    }}
                    placeholder="e.g. Biratnagar Central Warehouse"
                    className={`w-full px-4 py-2.5 text-sm rounded-xl bg-background border ${
                      fieldErrors.name ? 'border-destructive' : 'border-border/80'
                    } text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40`}
                  />
                  {fieldErrors.name && (
                    <p className="text-[11px] text-destructive mt-1 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" />
                      {fieldErrors.name}
                    </p>
                  )}
                </div>

                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
                    Inventory Type *
                  </label>
                  <select
                    value={type}
                    onChange={(e) => setType(e.target.value as any)}
                    className="w-full px-4 py-2.5 text-sm rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40"
                  >
                    <option value="WAREHOUSE">Warehouse (Central Storage / Depot)</option>
                    <option value="STORE">Retail Store (Showroom / Walk-in)</option>
                    <option value="SUPPLIER">Supplier (Dropship Facility)</option>
                    <option value="IN_TRANSIT">In Transit (Cross-Dock Buffer)</option>
                  </select>
                </div>
              </div>

              {/* Row 2: Priority (String Name) */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="block text-xs font-semibold text-foreground">
                    Fulfillment Priority *
                  </label>
                  <span className="text-[11px] text-muted-foreground">
                    Order in which this store/warehouse fulfills orders
                  </span>
                </div>

                {/* Quick select priority pills */}
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  {['Primary', 'High', 'Normal', 'Secondary', 'Low'].map((tier) => (
                    <button
                      key={tier}
                      type="button"
                      onClick={() => {
                        setPriorityLabel(tier);
                        if (fieldErrors.priority) {
                          setFieldErrors({ ...fieldErrors, priority: undefined });
                        }
                      }}
                      className={`px-3 py-1 text-xs font-medium rounded-lg border transition-all ${
                        priorityLabel.toLowerCase() === tier.toLowerCase()
                          ? 'bg-primary text-primary-foreground border-primary shadow-xs font-semibold'
                          : 'bg-muted/50 text-muted-foreground border-border/70 hover:text-foreground hover:bg-muted'
                      }`}
                    >
                      {tier}
                    </button>
                  ))}
                </div>

                <input
                  type="text"
                  value={priorityLabel}
                  onChange={(e) => {
                    setPriorityLabel(e.target.value);
                    if (fieldErrors.priority) {
                      setFieldErrors({ ...fieldErrors, priority: undefined });
                    }
                  }}
                  placeholder="e.g. Primary, High, Normal, Secondary"
                  className={`w-full px-4 py-2.5 text-sm rounded-xl bg-background border ${
                    fieldErrors.priority ? 'border-destructive' : 'border-border/80'
                  } text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40`}
                />
                {fieldErrors.priority && (
                  <p className="text-[11px] text-destructive mt-1 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />
                    {fieldErrors.priority}
                  </p>
                )}
              </div>

              {/* Row 3: City & Country */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
                    City (Optional)
                  </label>
                  <input
                    type="text"
                    value={city}
                    onChange={(e) => setCity(e.target.value)}
                    placeholder="e.g. Biratnagar, Kathmandu"
                    className="w-full px-4 py-2.5 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1.5">
                    Country (Optional)
                  </label>
                  <input
                    type="text"
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                    placeholder="e.g. Nepal, USA"
                    className="w-full px-4 py-2.5 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40"
                  />
                </div>
              </div>

              {/* Row 4: Sellable Checkbox - Clean primary styling and clear description */}
              <div
                onClick={() => setSellable(!sellable)}
                className="p-3.5 rounded-xl border border-border/80 bg-background/60 hover:bg-background transition-colors cursor-pointer flex items-start gap-3 select-none"
              >
                <div
                  className={`w-5 h-5 rounded-md flex items-center justify-center transition-all border shrink-0 mt-0.5 ${
                    sellable
                      ? 'bg-primary border-primary text-primary-foreground shadow-xs'
                      : 'bg-muted/60 border-border/80 hover:border-primary/50'
                  }`}
                >
                  {sellable && <Check className="w-3.5 h-3.5 stroke-[3]" />}
                </div>
                <div>
                  <div className="text-xs font-semibold text-foreground">
                    Available for Customer Orders & Sales
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
                    Check this if products stored here can be sold and shipped to customers.
                    (Uncheck for internal quarantine, repairs, or damaged goods).
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex justify-end gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={resetForm}
                  className="px-4 py-2 text-xs font-semibold rounded-xl border border-border/70 text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 flex items-center gap-2 shadow-xs disabled:opacity-50 transition-all cursor-pointer"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-4 h-4" />
                      {editingLocationId ? 'Update Inventory Location' : 'Save Inventory Location'}
                    </>
                  )}
                </button>
              </div>
            </form>
          )}

          {/* Delete Confirmation Banner */}
          {confirmDeleteId && (
            <div className="p-4 rounded-xl bg-destructive/10 border border-destructive/30 text-xs text-foreground flex items-center justify-between gap-4 animate-in fade-in">
              <div className="flex items-center gap-2.5">
                <ShieldAlert className="w-5 h-5 text-destructive shrink-0" />
                <div>
                  <div className="font-semibold text-destructive">Confirm Deleting Location?</div>
                  <div className="text-muted-foreground text-[11px]">
                    This location will be removed. Locations with active stock cannot be deleted.
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setConfirmDeleteId(null)}
                  className="px-3 py-1.5 rounded-lg border border-border/70 text-muted-foreground hover:text-foreground text-xs font-medium"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    const loc = locations.find((l) => l.id === confirmDeleteId);
                    if (loc) handleDelete(loc.id, loc.name);
                  }}
                  disabled={deletingLocationId === confirmDeleteId}
                  className="px-3 py-1.5 rounded-lg bg-destructive text-destructive-foreground hover:opacity-90 text-xs font-semibold flex items-center gap-1.5"
                >
                  {deletingLocationId === confirmDeleteId ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Deleting...
                    </>
                  ) : (
                    <>
                      <Trash2 className="w-3.5 h-3.5" />
                      Confirm Delete
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Existing Locations List with Generous Spacing and Clear Badges */}
          <div className="space-y-3">
            {locations.length === 0 ? (
              <div className="text-center py-12 rounded-2xl border border-dashed border-border/80 bg-muted/10 space-y-2">
                <div className="w-10 h-10 mx-auto rounded-xl bg-muted/60 flex items-center justify-center text-muted-foreground">
                  <MapPin className="w-5 h-5" />
                </div>
                <div className="text-xs font-semibold text-foreground">No inventory locations defined yet</div>
                <div className="text-[11px] text-muted-foreground max-w-sm mx-auto">
                  Add your primary warehouse or retail store to start managing stock and fulfillment routing.
                </div>
                <button
                  onClick={() => setIsOpenForm(true)}
                  className="mt-2 px-3.5 py-1.5 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 transition-all inline-flex items-center gap-1.5"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add First Location
                </button>
              </div>
            ) : (
              locations.map((loc) => {
                const priorityText = getPriorityDisplay(loc);
                return (
                  <div
                    key={loc.id}
                    className={`p-4 rounded-2xl border transition-all ${
                      editingLocationId === loc.id
                        ? 'border-primary bg-primary/5 shadow-sm ring-1 ring-primary/30'
                        : 'border-border/70 bg-card hover:border-primary/30'
                    } flex flex-col sm:flex-row sm:items-center justify-between gap-4`}
                  >
                    {/* Location Info */}
                    <div className="flex items-start gap-3.5 min-w-0">
                      <div className="w-10 h-10 rounded-xl bg-muted/80 border border-border/80 flex items-center justify-center shrink-0 mt-0.5">
                        {getTypeIcon(loc.type)}
                      </div>

                      <div className="min-w-0 space-y-1.5">
                        {/* Name & Priority */}
                        <div className="flex items-center gap-2.5 flex-wrap">
                          <h4 className="font-bold text-sm text-foreground truncate">
                            {loc.name}
                          </h4>
                          {/* Priority Pill */}
                          <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/25 flex items-center gap-1">
                            <span>⭐</span> Priority: {priorityText}
                          </span>
                        </div>

                        {/* Badges Row with Generous Spacing */}
                        <div className="flex items-center gap-2.5 flex-wrap text-xs">
                          {/* Type Badge */}
                          <span className="px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-muted/80 text-muted-foreground border border-border/70 flex items-center gap-1">
                            {getTypeLabel(loc.type)}
                          </span>

                          {/* Sellable Badge */}
                          {loc.sellable ? (
                            <span className="px-2.5 py-0.5 rounded-md text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                              <span>✅</span> Available to Sell
                            </span>
                          ) : (
                            <span className="px-2.5 py-0.5 rounded-md text-[11px] font-semibold bg-zinc-500/15 text-zinc-400 border border-zinc-500/30 flex items-center gap-1">
                              <span>🔒</span> Internal Storage Only
                            </span>
                          )}

                          {/* Address / City */}
                          {loc.address && (loc.address.city || loc.address.country) && (
                            <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                              <MapPin className="w-3 h-3 text-muted-foreground/80" />
                              {[loc.address.city, loc.address.country].filter(Boolean).join(', ')}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Actions: Edit & Delete */}
                    <div className="flex items-center gap-2 self-end sm:self-center shrink-0">
                      <button
                        onClick={() => handleStartEdit(loc)}
                        className="px-3 py-1.5 text-xs font-semibold rounded-xl border border-border/70 text-muted-foreground hover:text-foreground hover:bg-muted/70 transition-colors flex items-center gap-1.5"
                        title="Edit Location"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                        <span>Edit</span>
                      </button>

                      <button
                        onClick={() => setConfirmDeleteId(loc.id)}
                        className="p-2 text-xs font-semibold rounded-xl border border-border/70 text-muted-foreground hover:text-destructive hover:border-destructive/40 hover:bg-destructive/10 transition-colors"
                        title="Delete Location"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-border/60 flex items-center justify-end bg-card/90">
          <button
            onClick={onClose}
            className="px-5 py-2 text-xs font-semibold rounded-xl bg-muted hover:bg-muted/80 text-foreground transition-colors cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};

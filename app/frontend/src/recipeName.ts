import type {Data} from './api';

/** Expand legacy catalog titles for display without rewriting saved plans. */
export function recipeName(recipe:Data):string {
 if(!recipe.name?.includes('炖饭'))return recipe.name??'';
 const names=(recipe.items??[])
  .filter((item:Data)=>item.food_id!=='usda-171413'&&item.name!=='橄榄油')
  .map((item:Data)=>(item.name??'').split(/[（(]/)[0].trim()).filter(Boolean);
 return names.length?names.join('、'):recipe.name;
}
